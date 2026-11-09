"""Daily briefing 离线测试共享替身（确定性 stub，零网络零进程）。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from magent.checkpoint.models import canonical_json, checksum_of
from magent.mcp.fake import FakeMcpServer, FakeToolDefinition, InMemoryMcpTransport, fake_outcome
from magent.mcp.transport import McpCallOutcome

from apps.vulntell.domain.models import RawSourceRecord
from apps.vulntell.pipeline.daily import DailyBriefingConfig, DailyBriefingRunner

WINDOW_END = dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)
WINDOW_START = WINDOW_END - dt.timedelta(days=7)
WINDOW_DAYS = (WINDOW_END - WINDOW_START).days

OSV_CVE = "CVE-2024-3094"          # KEV stub 与 MCP fake 路径共用（去重合并演示）
KEV_ONLY_CVE = "CVE-2024-32030"    # 仅 KEV 路径观察到的漏洞


def osv_record(vid: str = OSV_CVE, *, modified: str = "2024-05-28T00:00:00+00:00",
               published: str = "2024-05-27T00:00:00+00:00") -> dict:
    """最小原始 OSV 记录（供 fake server 与 REST stub 共用同一份字节）。"""
    return {
        "id": vid,
        "aliases": [vid, "GHSA-fake-0001-0002"],
        "summary": "xz backdoor in liblzma",
        "details": "A backdoor was introduced in xz.",
        "published": published,
        "modified": modified,
        "affected": [{"package": {"ecosystem": "PyPI", "name": "example-pkg"}}],
        "references": [{"type": "WEB", "url": "https://example.com/xz-advisory"}],
        "database_specific": {"cwe_ids": ["CWE-506"]},
        "severity": [{"type": "CVSS_V3", "score": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
    }


def stub_record(source: str, rid: str, *, cve: str | None, published: str,
                modified: str, added: str) -> RawSourceRecord:
    """构造一个跨来源可比对的最小 normalized-payload RawSourceRecord。"""
    payload: dict[str, Any] = {
        "cve_id": cve,
        "title": f"{source} report for {cve or rid}",
        "description": f"collective stub record {rid}",
        "published_at": published,
        "modified_at": modified,
        "source_added_at": added,
        "affected": ["PyPI:example-pkg"],
        "aliases": [cve] if cve else [],
        "cwe": [],
        "references": [{"url": "https://example.com/ref", "ref_type": "WEB"}],
        "cvss_score": 7.5,
        "cvss_vector": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        "cvss_version": "3.x",
    }
    return RawSourceRecord(
        source=source,
        record_id=rid,
        observed_at=WINDOW_END,
        dataset_id="vulntell-daily",
        dataset_version="dev",
        payload=payload,
        payload_hash=checksum_of(canonical_json(payload)),
    )


class StubAdapter:
    """CollectAgent 兼容的最小 stub（返回预置记录；可注入异常）。"""

    def __init__(self, source: str, records: list[RawSourceRecord],
                 raise_message: str | None = None) -> None:
        self.source = source
        self._records = records
        self._raise_message = raise_message
        self.last_summary: dict = {"requested": len(records), "fetched": len(records), "failed": {}}

    async def fetch(self, dataset_id: str, dataset_version: str, observed_at: dt.datetime):
        if self._raise_message is not None:
            raise RuntimeError(self._raise_message)
        return [r.model_copy(update={"dataset_id": dataset_id, "dataset_version": dataset_version})
                for r in self._records]

    async def aclose(self) -> None:
        return None


def kev_stub() -> StubAdapter:
    """KEV stub：同窗口两条贡献记录（其中一条与 OSV 路径同 CVE）。"""
    return StubAdapter("cisa_kev", [
        stub_record("cisa_kev", OSV_CVE, cve=OSV_CVE,
                    published="2024-05-27", modified="2024-05-27", added="2024-05-27"),
        stub_record("cisa_kev", KEV_ONLY_CVE, cve=KEV_ONLY_CVE,
                    published="2024-05-27", modified="2024-05-28", added="2024-05-27"),
    ])


def failing_stub(source: str = "cisa_kev") -> StubAdapter:
    return StubAdapter(source, [], raise_message="cisa_kev: feed unavailable (stub)")


def osv_fake_server(overrides: dict[str, dict] | None = None,
                    *, fail_ids: set[str] | None = None) -> FakeMcpServer:
    """进程内 OSV fake server（``osv_get_payload`` 工具）。"""
    overrides = overrides or {}
    fail_ids = fail_ids or set()

    async def handler(args: dict) -> McpCallOutcome:
        vid = args["vuln_id"]
        if vid in fail_ids:
            return fake_outcome(is_error=True, error_kind="permanent", error_message=f"not found {vid}")
        if vid in overrides:
            return fake_outcome(structured={"result": overrides[vid]})
        return fake_outcome(structured={"result": osv_record(vid)})

    return FakeMcpServer("osv", [
        FakeToolDefinition(
            name="osv_get_payload",
            handler=handler,
            description="raw OSV record read (offline fake)",
            input_schema={"type": "object", "properties": {"vuln_id": {"type": "string"}}},
            read_only=True,
        )
    ])


def osv_mcp_adapter(vuln_ids: tuple[str, ...] = (OSV_CVE,)):
    """构建注入 fake transport 的 MCP 采集适配器。"""
    from apps.vulntell.sources.mcp_adapter import McpSourceAdapter

    server = osv_fake_server()

    def factory():
        return InMemoryMcpTransport(server)

    adapter = McpSourceAdapter(
        source="osv_mcp",
        tool_name="osv_get_payload",
        vuln_ids=vuln_ids,
        transport_factory=factory,
        window_start=WINDOW_START,
        call_timeout=5.0,
    )
    return adapter, server, factory


def stub_http_fetch(canned: dict[str, dict] | None = None, fail_ids: set[str] | None = None):
    """REST 直连 stub：按 URL 尾段命中 canned 记录；fail_ids 抛 HTTP 404 型异常。"""
    canned = canned or {}
    fail_ids = fail_ids or set()

    class HttpErrorStub(Exception):
        pass

    async def fetch(url: str) -> dict:
        vid = url.rsplit("/", 1)[-1]
        if vid in fail_ids:
            raise HttpErrorStub(f"HTTP 404 for {vid}")
        if vid in canned:
            return canned[vid]
        return osv_record(vid)

    return fetch


async def run_offline_briefing(tmp_path, *, sources=("cisa_kev", "osv_mcp"),
                               osv_ids: tuple[str, ...] = (OSV_CVE,)):
    """在调用方事件循环内跑一次注入全部替身的完整 daily workflow。"""
    kev = failing_stub("cisa_kev") if "cisa_kev" not in sources else kev_stub()
    adapter_map: dict[str, Any] = {}
    factory = None
    server = None
    if "osv_mcp" in sources:
        osv_adapter, server, factory = osv_mcp_adapter(vuln_ids=osv_ids)
        adapter_map["osv_mcp"] = osv_adapter
    if "cisa_kev" in sources:
        adapter_map["cisa_kev"] = kev

    config = DailyBriefingConfig(
        run_date=dt.date(2024, 6, 1),
        window_days=WINDOW_DAYS,
        sources=tuple(sources),
        osv_sample_ids=osv_ids,
        out_dir=tmp_path / "out",
        db=str(tmp_path / "daily.sqlite3"),
        checkpoint=":memory:",
    )
    runner = DailyBriefingRunner(
        config,
        adapters=adapter_map,
        http_fetch=stub_http_fetch(),
        mcp_transport_factory=factory,
    )
    result = await runner.run()
    return result, adapter_map, server
