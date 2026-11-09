"""MCP 采集适配器（apps.vulntell.sources.mcp_adapter）离线测试。

全部走 ``magent.mcp.fake`` 的进程内替身：零网络、零 SDK 导入、确定性。
覆盖：payload 映射契约、信封兼容、失败隔离与整体降级、窗口过滤、
采集摘要、幂等关闭。
"""

from __future__ import annotations

import datetime as dt

import pytest

from magent.mcp.fake import FakeMcpServer, FakeToolDefinition, InMemoryMcpTransport, fake_outcome
from magent.mcp.transport import McpCallOutcome

from apps.vulntell.sources.mcp_adapter import (
    McpSourceAdapter,
    McpSourceAdapterError,
    parse_osv_call,
    payload_from_osv,
)

_WINDOW_END = dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)
_WINDOW_START = _WINDOW_END - dt.timedelta(days=7)


def _osv_record(vid: str = "CVE-2024-3094", *, modified: str = "2024-05-28T00:00:00+00:00",
                published: str = "2024-05-27T00:00:00+00:00") -> dict:
    return {
        "id": vid,
        "aliases": [vid, "GHSA-xxxx-yyyy-zzzz"],
        "summary": "xz backdoor in liblzma",
        "details": "A backdoor was introduced in xz.",
        "published": published,
        "modified": modified,
        "affected": [
            {"package": {"ecosystem": "PyPI", "name": "example-pkg"}},
        ],
        "references": [{"type": "WEB", "url": "https://www.openwall.com/xz"}],
        "database_specific": {"cwe_ids": ["CWE-506"]},
        "severity": [{"type": "CVSS_V3", "score": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
    }


def _server(overrides: dict[str, dict] | None = None, *, fail_ids: set[str] | None = None) -> FakeMcpServer:
    overrides = overrides or {}
    fail_ids = fail_ids or set()

    async def handler(args: dict) -> McpCallOutcome:
        vid = args["vuln_id"]
        if vid in fail_ids:
            return fake_outcome(is_error=True, error_kind="permanent", error_message=f"not found {vid}")
        payload = overrides.get(vid, _osv_record(vid))
        return fake_outcome(structured={"result": payload})

    return FakeMcpServer("osv", [
        FakeToolDefinition(
            name="osv_get_payload",
            handler=handler,
            description="raw OSV record read",
            input_schema={"type": "object", "properties": {"vuln_id": {"type": "string"}}},
            read_only=True,
        )
    ])


def _factory(server: FakeMcpServer):  # noqa: ANN202 - 测试内的 lambda 注入
    return lambda: InMemoryMcpTransport(server)


def _adapter(server: FakeMcpServer, vuln_ids: tuple[str, ...] = ("CVE-2024-3094",)) -> McpSourceAdapter:
    return McpSourceAdapter(
        source="osv_mcp",
        tool_name="osv_get_payload",
        vuln_ids=vuln_ids,
        transport_factory=_factory(server),
        window_start=_WINDOW_START,
        call_timeout=5.0,
    )


# ---------------------------------------------------------------- 解析与映射


def test_parse_osv_call_accepts_both_envelopes():
    envelope = McpCallOutcome(structured={"result": _osv_record()})
    bare = McpCallOutcome(structured=_osv_record("CVE-2021-44228"))
    assert parse_osv_call(envelope) is not None
    assert parse_osv_call(bare) is not None
    assert parse_osv_call(McpCallOutcome(content_text=("not json",))) is None
    assert parse_osv_call(fake_outcome(is_error=True)) is None


def test_payload_from_osv_maps_vulntell_contract():
    payload = payload_from_osv(_osv_record())
    assert payload["cve_id"] == "CVE-2024-3094"
    assert payload["title"] == "xz backdoor in liblzma"
    assert payload["published_at"] == "2024-05-27T00:00:00+00:00"
    assert payload["modified_at"] == "2024-05-28T00:00:00+00:00"
    assert payload["source_added_at"] is None  # OSV 无此字段：按缺失记账
    assert payload["affected"] == ["PyPI:example-pkg"]
    assert payload["cwe"] == ["CWE-506"]
    assert payload["cvss_vector"] and payload["cvss_score"] is None  # score 位是向量本体
    assert payload["references"][0]["url"] == "https://www.openwall.com/xz"


# ---------------------------------------------------------------- fetch 行为


async def test_fetch_returns_raw_source_records_with_hash():
    server = _server()
    adapter = _adapter(server)
    records = await adapter.fetch("vulntell-daily", "dev", _WINDOW_END)
    assert len(records) == 1
    rec = records[0]
    assert rec.source == "osv_mcp"
    assert rec.record_id == "CVE-2024-3094"
    assert rec.payload["cve_id"] == "CVE-2024-3094"
    assert len(rec.payload_hash) == 64
    assert server.call_log == [("osv_get_payload", {"vuln_id": "CVE-2024-3094"})]
    assert adapter.last_summary == {"requested": 1, "fetched": 1, "failed": {}, "skipped_window": 0}


async def test_fetch_skips_single_failures_and_degrades_on_all_failed():
    server = _server(fail_ids={"CVE-2021-33333333"})
    adapter = _adapter(server, vuln_ids=("CVE-2021-33333333", "CVE-2024-3094"))
    records = await adapter.fetch("vulntell-daily", "dev", _WINDOW_END)
    assert [r.record_id for r in records] == ["CVE-2024-3094"]
    assert "CVE-2021-33333333" in adapter.last_summary["failed"]

    all_fail = _adapter(_server(fail_ids={"CVE-2024-3094"}))
    with pytest.raises(McpSourceAdapterError):
        await all_fail.fetch("vulntell-daily", "dev", _WINDOW_END)


async def test_fetch_window_filter_keeps_only_windowed_records():
    oldest = _osv_record("OLD-1", modified="2020-01-01T00:00:00+00:00",
                         published="2019-12-01T00:00:00+00:00")
    stamppless = _osv_record("no-stamp", modified="", published="")
    server = _server(overrides={"OLD-1": oldest, "no-stamp": stamppless})
    adapter = _adapter(server, vuln_ids=("OLD-1", "no-stamp", "CVE-2024-3094"))
    records = await adapter.fetch("vulntell-daily", "dev", _WINDOW_END)
    assert [r.record_id for r in records] == ["CVE-2024-3094"]
    assert adapter.last_summary["skipped_window"] == 2


async def test_fetch_all_successful_but_out_of_window_is_empty_not_failure():
    old = _osv_record("OLD-1", modified="2020-01-01T00:00:00+00:00", published="2019-12-01T00:00:00+00:00")
    adapter = _adapter(_server(overrides={"OLD-1": old}), vuln_ids=("OLD-1",))
    records = await adapter.fetch("vulntell-daily", "dev", _WINDOW_END)
    assert records == []
    assert adapter.last_summary["failed"] == {}
    assert adapter.last_summary["skipped_window"] == 1


async def test_fetch_degrades_for_unknown_tool():
    bad = FakeMcpServer("osv", [])  # 不含目标工具
    adapter = _adapter(bad)
    with pytest.raises(McpSourceAdapterError):
        await adapter.fetch("vulntell-daily", "dev", _WINDOW_END)


async def test_aclose_idempotent_and_fetch_after_close_raises():
    adapter = _adapter(_server())
    await adapter.aclose()
    await adapter.aclose()  # 幂等
    with pytest.raises(McpSourceAdapterError):
        await adapter.fetch("vulntell-daily", "dev", _WINDOW_END)
