"""OSV 双路径一致性探针（阶段 10 桥接，Task daily.3）。

同一 OSV.dev 端点走两条采集路径：
- REST 直连（``http_fetch`` 注入；live 用 httpx 懒导入，离线注入桩）；
- MCP 协议（``transport_factory`` 注入；live 用真实 stdio server，离线用 fake）。

对每个样本 CVE ID 产出对比行：原始载荷 canonical-hash 是否一致、归一化
payload 字段集是否一致、两侧延迟与失败形态。失败也是证据：该 ID 在两条
路径上应当**同形失败**（REST HTTP 状态 vs MCP ``isError`` outcome）。

约束：
- 这是 VulnTell（L3）使用 magent MCP transport 接缝的数据面只读探针；
- 不写库、不改状态；结果只进 `dual_path.json` 与 dashboard；
- 延迟在客户端进程测量（含协议开销），对路径公平（同一时钟）。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, Sequence

from magent.checkpoint.models import canonical_json, checksum_of
from magent.mcp.transport import McpCallOutcome, McpTransport

from apps.vulntell.sources.mcp_adapter import payload_from_osv, parse_osv_call

HttpFetch = Callable[[str], Awaitable[dict]]
TransportFactory = Callable[[], McpTransport]

OSV_RECORD_URL = "https://api.osv.dev/v1/vulns/"


@dataclass
class DualPathRow:
    """一条样本 ID 的双路径对比结果（可 JSON 序列化）。"""

    cve_id: str
    rest_ok: bool = False
    mcp_ok: bool = False
    payload_hash_equal: Optional[bool] = None
    fields_equal: Optional[bool] = None
    rest_latency_ms: Optional[float] = None
    mcp_latency_ms: Optional[float] = None
    rest_error: Optional[str] = None
    mcp_error: Optional[str] = None
    rest_hash: Optional[str] = None
    mcp_hash: Optional[str] = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _compare_fields(rest_payload: dict, mcp_payload: dict) -> bool:
    """归一化后的字段级一致性（对时间戳解析、别名排序等保持同一规则）。"""
    return {k: v for k, v in rest_payload.items()} == {k: v for k, v in mcp_payload.items()}


class DualPathProbe:
    """对样本 ID 列表执行 REST/MCP 双路径读取与一致性对比。"""

    def __init__(
        self,
        *,
        cve_ids: Sequence[str],
        mcp_transport_factory: TransportFactory,
        http_fetch: HttpFetch,
        tool_name: str = "osv_get_payload",
        call_timeout: float = 60.0,
    ) -> None:
        self._ids = tuple(dict.fromkeys(str(v).strip() for v in cve_ids if str(v).strip()))
        self._mcp_factory = mcp_transport_factory
        self._http_fetch = http_fetch
        self._tool_name = tool_name
        self._call_timeout = call_timeout

    async def _rest_fetch(self, vid: str) -> tuple[dict, float, Optional[str]]:
        url = OSV_RECORD_URL + vid
        start = time.perf_counter()
        try:
            record = await asyncio.wait_for(self._http_fetch(url), timeout=self._call_timeout)
            return record, (time.perf_counter() - start) * 1000.0, None
        except Exception as exc:  # noqa: BLE001 - 失败形态也是对照证据
            return {}, (time.perf_counter() - start) * 1000.0, f"{type(exc).__name__}: {exc}"

    async def _mcp_fetch(
        self, transport: McpTransport, vid: str
    ) -> tuple[Optional[dict], float, Optional[str]]:
        start = time.perf_counter()
        try:
            outcome: McpCallOutcome = await asyncio.wait_for(
                transport.call_tool(self._tool_name, {"vuln_id": vid}),
                timeout=self._call_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            return None, (time.perf_counter() - start) * 1000.0, f"{type(exc).__name__}: {exc}"
        latency = (time.perf_counter() - start) * 1000.0
        if outcome.is_error:
            return None, latency, outcome.error_message or outcome.error_kind or "tool error"
        record = parse_osv_call(outcome)
        if record is None:
            return None, latency, "unparseable outcome"
        return record, latency, None

    async def run(self) -> dict:
        """执行探针；返回 ``{"summary": ..., "rows": [...]}``。"""
        transport: Optional[McpTransport] = None
        mcp_setup_error: Optional[str] = None
        if self._ids:
            try:
                transport = self._mcp_factory()
                await transport.connect()
            except Exception as exc:  # noqa: BLE001 - 侧失败记录为全行 MCP 失败
                mcp_setup_error = f"{type(exc).__name__}: {exc}"
        try:
            rows: list[DualPathRow] = []
            for vid in self._ids:
                row = DualPathRow(cve_id=vid)
                rest_record, rest_ms, rest_err = await self._rest_fetch(vid)
                row.rest_latency_ms = round(rest_ms, 1)
                row.rest_ok = rest_err is None and bool(rest_record.get("id"))
                if rest_err is not None:
                    row.rest_error = rest_err
                else:
                    row.rest_hash = checksum_of(canonical_json(rest_record))

                if transport is None:
                    row.mcp_error = mcp_setup_error or "transport unavailable"
                else:
                    mcp_record, mcp_ms, mcp_err = await self._mcp_fetch(transport, vid)
                    row.mcp_latency_ms = round(mcp_ms, 1)
                    row.mcp_ok = mcp_err is None and mcp_record is not None
                    if mcp_err is not None:
                        row.mcp_error = mcp_err
                    else:
                        assert mcp_record is not None  # 由 mcp_ok 保证
                        row.mcp_hash = checksum_of(canonical_json(mcp_record))
                        row.payload_hash_equal = row.rest_hash == row.mcp_hash if row.rest_ok else None
                        row.fields_equal = (
                            _compare_fields(payload_from_osv(rest_record), payload_from_osv(mcp_record))
                            if row.rest_ok
                            else None
                        )
                rows.append(row)
            summary = {
                "sample_size": len(rows),
                "both_ok": sum(1 for r in rows if r.rest_ok and r.mcp_ok),
                "hash_equal": sum(
                    1 for r in rows if r.payload_hash_equal is True
                ),
                "fields_equal": sum(1 for r in rows if r.fields_equal is True),
                "same_shape_failures": sum(
                    1 for r in rows if not r.rest_ok and not r.mcp_ok
                ),
                "tool_name": self._tool_name,
            }
            return {"summary": summary, "rows": [r.to_dict() for r in rows]}
        finally:
            if transport is not None:
                await transport.close()
