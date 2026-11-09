"""VulnTell MCP 采集适配器（阶段 10 桥接，Task daily.2）。

把 magent MCP transport 接缝（``McpTransport`` / ``McpCallOutcome``）封装成
VulnTell ``CollectAgent`` 需要的数据源接口 ``fetch(dataset_id, dataset_version,
observed_at) -> list[RawSourceRecord]``——与 LiveSourceAdapter 同构，复用既有
图拓扑、归一化、去重、持久化与评估管线，不改采集 Agent。

约束（沿 VulnTell/phase-10 双方既有纪律）：
- 这是数据面客户端：不经 ``McpToolLoader``（它是 ToolRegistry 的注册面），
  直接使用 transport 接缝；tool 名与 schema 由调用方显式约定（自持 server）；
- transport factory 注入：live 用真实 stdio factory，测试用
  ``magent.mcp.fake.InMemoryMcpTransport``——零网络离线确定性；
- FastMCP(SDK 1.30) 把返回值包进 ``structuredContent:{"result": ...}``：
  解析同时兼容信封与裸字典两种形态；
- 单条 ID 失败只跳过并计数；全部失败才抛错，让 CollectAgent 统一降级
  （source_status=failed，不丢弃其他来源分支）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Sequence

from magent.checkpoint.models import canonical_json, checksum_of
from magent.mcp.transport import McpCallOutcome, McpTransport

from apps.vulntell.domain.models import RawSourceRecord

TransportFactory = Callable[[], McpTransport]


class McpSourceAdapterError(RuntimeError):
    """MCP 采集路径整体失败（CollectAgent 将降级为该来源 failed）。"""


def parse_osv_call(outcome: McpCallOutcome) -> Optional[dict]:
    """从一次 ``osv_get_payload`` 调用结果提取原始 OSV JSON 字典。

    兼容两种信封形态：FastMCP 的 ``{"result": {...}}`` 与裸记录字典。
    非 dict / 缺 ``id`` 返回 ``None``（由调用方决定计数或降级）。
    """
    record: Any = None
    if isinstance(outcome.structured, dict):
        candidate = outcome.structured.get("result")
        record = candidate if isinstance(candidate, dict) else outcome.structured
    if record is None:
        try:
            parsed = __import__("json").loads(outcome.text)
        except Exception:  # noqa: BLE001 - 解析失败按缺记录处理
            return None
        if isinstance(parsed, dict):
            record = parsed.get("result") if isinstance(parsed.get("result"), dict) else parsed
    if not isinstance(record, dict) or not record.get("id"):
        return None
    return record


def payload_from_osv(record: dict) -> dict:
    """把原始 OSV JSON 映射为 VulnTell ``normalize_record`` 认的 payload 形态。

    OSV 无 source_added_at 字段——保持缺失（normalize 会按既有规则记录
    ``source_added_at missing`` 低危告警，与其他来源一致，不用默认值掩盖）。
    """
    aliases = [str(a).strip() for a in (record.get("aliases") or []) if str(a).strip()]
    cve_id = next((a for a in aliases if a.startswith("CVE-")), None)

    references = []
    for ref in record.get("references") or []:
        if isinstance(ref, dict) and ref.get("url"):
            references.append({"url": ref["url"], "ref_type": ref.get("type") or None})

    affected = []
    for aff in record.get("affected") or []:
        pkg = (aff or {}).get("package") or {}
        if pkg.get("ecosystem") and pkg.get("name"):
            affected.append(f"{pkg['ecosystem']}:{pkg['name']}")

    # CWE：只在格式合法时携带（规则同 normalize.is_cwe）。
    dw = record.get("database_specific") or {}
    cwe_raw = dw.get("cwe_ids") or []
    if not isinstance(cwe_raw, list):
        cwe_raw = [cwe_raw]
    cwe = [str(c).strip() for c in cwe_raw
           if str(c).startswith(("CWE-", "NVD-CWE-"))]

    cvss_score: Optional[float] = None
    cvss_vector: Optional[str] = None
    for sev in record.get("severity") or []:
        if not isinstance(sev, dict):
            continue
        score = sev.get("score")
        vec = sev.get("vector")
        if vec is None and isinstance(score, str) and "/" in score:
            # OSV 惯例：CVSS_V3 的 severity.score 存向量本体
            vec, score = score, None
        if score is not None and cvss_score is None:
            try:
                cvss_score = float(score)
            except (TypeError, ValueError):
                pass
        if vec is not None and cvss_vector is None:
            cvss_vector = str(vec)
        if cvss_score is not None and cvss_vector is not None:
            break

    return {
        "cve_id": cve_id,
        "title": record.get("summary") or None,
        "description": record.get("details") or None,
        "published_at": record.get("published"),
        "modified_at": record.get("modified") or record.get("published"),
        "source_added_at": None,
        "references": references,
        "affected": affected,
        "aliases": aliases,
        "cwe": cwe,
        "cwe_ids": list(cwe),
        "cvss_score": cvss_score,
        "cvss_vector": cvss_vector,
        "cvss_version": "3.x" if cvss_vector is not None else None,
    }


def _window_filter(record: dict, window_start: datetime, window_end: datetime) -> bool:
    stamp = record.get("modified") or record.get("published")
    if not stamp:
        return False
    try:
        iso = str(stamp).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return window_start <= parsed.astimezone(timezone.utc) < window_end


class McpSourceAdapter:
    """经 MCP 协议采集 OSV 记录的数据面适配器（ ``CollectAgent`` 兼容）。"""

    def __init__(
        self,
        *,
        source: str,
        tool_name: str,
        vuln_ids: Sequence[str],
        transport_factory: TransportFactory,
        window_start: datetime,
        call_timeout: float = 60.0,
    ) -> None:
        self._source = source
        self._tool_name = tool_name
        self._vuln_ids = tuple(dict.fromkeys(str(v).strip() for v in vuln_ids if str(v).strip()))
        self._factory = transport_factory
        self._window_start = window_start
        self._call_timeout = call_timeout
        self._transport: Optional[McpTransport] = None
        self._closed = False
        # 供 runner/dashboard 读取的采集摘要（不进框架 State）。
        self.last_summary: dict = {
            "requested": len(self._vuln_ids),
            "fetched": 0,
            "failed": {},
            "skipped_window": 0,
        }

    async def _ensure_transport(self) -> McpTransport:
        if self._closed:
            raise McpSourceAdapterError(f"mcp source {self._source!r} already closed")
        if self._transport is None:
            transport = self._factory()
            await transport.connect()
            self._transport = transport
        return self._transport

    async def fetch(
        self, dataset_id: str, dataset_version: str, observed_at: datetime
    ) -> list[RawSourceRecord]:
        """按注入的样本 ID 列表调 ``tools/call``，产出 RawSourceRecord。"""
        transport = await self._ensure_transport()
        end = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
        window_start = self._window_start

        records: list[RawSourceRecord] = []
        failed: dict[str, str] = {}
        skipped_window = 0
        for vid in self._vuln_ids:
            try:
                outcome = await asyncio.wait_for(
                    transport.call_tool(self._tool_name, {"vuln_id": vid}),
                    timeout=self._call_timeout,
                )
            except asyncio.TimeoutError:
                failed[vid] = f"timeout after {self._call_timeout:.0f}s"
                continue
            except Exception as exc:  # noqa: BLE001 - transport/协议层失败计入该 ID
                failed[vid] = f"transport/{type(exc).__name__}: {exc}"
                continue
            record = parse_osv_call(outcome)
            if record is None:
                failed[vid] = outcome.error_message or outcome.error_kind or "unparseable outcome"
                continue
            if not _window_filter(record, window_start, end):
                skipped_window += 1
                continue
            payload = payload_from_osv(record)
            records.append(
                RawSourceRecord(
                    source=self._source,
                    record_id=str(record.get("id")),
                    observed_at=end,
                    dataset_id=dataset_id,
                    dataset_version=dataset_version,
                    payload=payload,
                    payload_hash=checksum_of(canonical_json(record)),
                )
            )

        self.last_summary = {
            "requested": len(self._vuln_ids),
            "fetched": len(records),
            "failed": failed,
            "skipped_window": skipped_window,
        }
        # 成功读取但全部落在窗口外是合法的空结果；只有每个请求都失败
        # （协议错误、传输错误或超时）才把来源降级为失败。
        if not records and self._vuln_ids and len(failed) == len(self._vuln_ids):
            raise McpSourceAdapterError(
                f"mcp source {self._source!r} produced no records; failures={failed}"
            )
        return records

    async def aclose(self) -> None:
        """关闭 transport；幂等。"""
        self._closed = True
        if self._transport is not None:
            await self._transport.close()
            self._transport = None
