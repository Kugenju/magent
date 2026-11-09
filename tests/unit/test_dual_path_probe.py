"""OSV 双路径一致性探针（apps.vulntell.sources.mcp_bridge）离线测试。

覆盖：hash 一致、字段一致、同形失败、单侧失败、汇总计数。
"""

from __future__ import annotations

import pytest

from apps.vulntell.sources.mcp_bridge import DualPathProbe
from apps.vulntell.sources.mcp_adapter import payload_from_osv

from _daily_helpers import OSV_CVE, osv_fake_server, osv_record, stub_http_fetch


def _probe(tmp_path, *, cve_ids=(OSV_CVE,), canned=None, fail_ids=None, server=None):
    server = server or osv_fake_server(fail_ids=fail_ids)

    def factory():
        from magent.mcp.fake import InMemoryMcpTransport

        return InMemoryMcpTransport(server)

    probe = DualPathProbe(
        cve_ids=tuple(cve_ids),
        mcp_transport_factory=factory,
        http_fetch=stub_http_fetch(canned, fail_ids),
        tool_name="osv_get_payload",
        call_timeout=5.0,
    )
    return probe


async def test_dual_path_equality_on_identical_payloads(tmp_path):
    probe = _probe(tmp_path)
    result = await probe.run()
    assert result["summary"]["sample_size"] == 1
    assert result["summary"]["both_ok"] == 1
    assert result["summary"]["hash_equal"] == 1
    assert result["summary"]["fields_equal"] == 1
    row = result["rows"][0]
    assert row["cve_id"] == OSV_CVE
    assert row["payload_hash_equal"] is True
    assert row["fields_equal"] is True
    assert row["rest_ok"] and row["mcp_ok"]
    assert row["rest_latency_ms"] is not None and row["mcp_latency_ms"] is not None


async def test_dual_path_counts_same_shape_failures(tmp_path):
    """ID 不在 OSV 索引：REST 404 与 MCP isError —— 同形失败。"""
    probe = _probe(tmp_path, cve_ids=("CVE-9999-00001",), fail_ids={"CVE-9999-00001"})
    result = await probe.run()
    row = result["rows"][0]
    assert row["rest_ok"] is False and row["mcp_ok"] is False
    assert row["payload_hash_equal"] is None and row["fields_equal"] is None
    assert result["summary"]["same_shape_failures"] == 1


async def test_dual_path_single_side_failure_is_not_hash_equal(tmp_path):
    """单侧失败（REST 路径 down）不会伪造 hash 结论。"""
    from magent.mcp.fake import InMemoryMcpTransport

    overrides = {OSV_CVE: dict(osv_record(OSV_CVE))}

    async def broken_rest(url: str) -> dict:
        raise RuntimeError("rest path down")

    probe = DualPathProbe(
        cve_ids=(OSV_CVE,),
        mcp_transport_factory=lambda: InMemoryMcpTransport(osv_fake_server(overrides)),
        http_fetch=broken_rest,
        tool_name="osv_get_payload",
        call_timeout=5.0,
    )
    result = await probe.run()
    row = result["rows"][0]
    assert row["rest_ok"] is False
    assert row["mcp_ok"] is True
    assert row["payload_hash_equal"] is None
    assert result["summary"]["both_ok"] == 0


def test_payload_field_comparison_rule():
    a = payload_from_osv(osv_record(OSV_CVE))
    b = dict(a)
    b["title"] = "mutated"
    assert a != b  # 字段集比较发现差异
