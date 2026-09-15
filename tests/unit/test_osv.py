"""VulnTell OSV.dev 适配器测试（阶段 6，Task 6.1）。"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from datetime import datetime, timezone, timedelta

import pytest

from apps.vulntell.sources.osv import OSVAdapter, OSVConfig
from apps.vulntell.sources.errors import SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRequest


def _make_request(**kwargs) -> SourceRequest:
    now = datetime.now(timezone.utc)
    defaults = {
        "source": "osv",
        "dataset_id": "test",
        "dataset_version": "1.0",
        "window_start": now - timedelta(days=30),
        "window_end": now,
        "page_size": 100,
    }
    defaults.update(kwargs)
    return SourceRequest(**defaults)


class MockTransport:
    """Mock HTTP transport for testing."""

    def __init__(self, response: dict, status_code: int = 200) -> None:
        self._response = response
        self._status_code = status_code

    async def __call__(self, **kwargs) -> dict:
        return {
            "status_code": self._status_code,
            "data": self._response if self._status_code == 200 else None,
            "error": "error" if self._status_code != 200 else None,
        }


def test_osv_adapter_basic():
    """基本功能：返回正确记录。"""
    response = {
        "vulns": [
            {"id": "GHSA-2024-0001", "summary": "Test vulnerability 1"},
            {"id": "GHSA-2024-0002", "summary": "Test vulnerability 2"},
        ],
    }
    transport = MockTransport(response)
    adapter = OSVAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 2
    assert result.source == "osv"
    assert not result.has_more


def test_osv_adapter_pagination():
    """分页：has_more 和 next_cursor。"""
    response = {
        "vulns": [
            {"id": f"GHSA-2024-{i:04d}", "summary": f"Vulnerability {i}"}
            for i in range(100)
        ],
        "next_page_token": "next_token_123",
    }
    transport = MockTransport(response)
    adapter = OSVAdapter(transport=transport)
    req = _make_request(page_size=100)

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 100
    assert result.has_more
    assert result.next_cursor == "next_token_123"


def test_osv_adapter_cursor():
    """游标：从指定位置继续。"""
    response = {
        "vulns": [
            {"id": f"GHSA-2024-{i:04d}", "summary": f"Vulnerability {i}"}
            for i in range(50)
        ],
    }
    transport = MockTransport(response)
    adapter = OSVAdapter(transport=transport)
    req = _make_request(page_size=100)

    result = asyncio.run(adapter.fetch_page(req, cursor="next_token_123"))
    assert isinstance(result, SourcePage)
    assert result.record_count == 50
    assert not result.has_more


def test_osv_adapter_rate_limit():
    """429 限流：返回 rate_limited 错误。"""
    transport = MockTransport({}, status_code=429)
    adapter = OSVAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.RATE_LIMITED


def test_osv_adapter_timeout():
    """超时：返回 timeout 错误。"""
    async def timeout_transport(**kwargs):
        raise TimeoutError("Request timed out")

    adapter = OSVAdapter(transport=timeout_transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.TIMEOUT


def test_osv_adapter_empty_response():
    """空响应：返回空页。"""
    response = {"vulns": []}
    transport = MockTransport(response)
    adapter = OSVAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 0
    assert not result.has_more


def test_osv_config_defaults():
    """配置默认值。"""
    config = OSVConfig()
    assert "osv.dev" in config.endpoint
    assert config.timeout_seconds == 30.0
    assert config.page_size == 100


def test_osv_adapter_ecosystem():
    """生态系统信息提取。"""
    response = {
        "vulns": [
            {
                "id": "GHSA-2024-0001",
                "summary": "Test vulnerability",
                "affected": [
                    {
                        "package": {
                            "ecosystem": "npm",
                            "name": "test-package",
                        },
                        "ranges": [
                            {
                                "type": "SEMVER",
                                "events": [
                                    {"introduced": "0.0.1"},
                                    {"fixed": "0.0.2"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    transport = MockTransport(response)
    adapter = OSVAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 1
    record = result.records[0]
    assert record.payload["packages"][0]["ecosystem"] == "npm"
    assert record.payload["packages"][0]["name"] == "test-package"


def test_osv_bulk_snapshot_pagination_and_window():
    """Official all.zip snapshots are parsed and paged without querybatch."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("GHSA-1.json", json.dumps({"id": "GHSA-1", "summary": "in",
            "modified": "2025-01-01T00:00:00Z"}))
        zf.writestr("GHSA-2.json", json.dumps({"id": "GHSA-2", "summary": "out",
            "modified": "2020-01-01T00:00:00Z"}))

    class BulkTransport:
        async def __call__(self, **kwargs):
            return {"status_code": 200, "content": buf.getvalue()}

    adapter = OSVAdapter(config=OSVConfig(use_bulk=True, bulk_ecosystems=("PyPI",), page_size=1), transport=BulkTransport())
    req = _make_request(window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                        window_end=datetime(2026, 1, 1, tzinfo=timezone.utc), page_size=1)
    first = asyncio.run(adapter.fetch_page(req))
    assert isinstance(first, SourcePage)
    assert first.record_count == 1 and not first.has_more
