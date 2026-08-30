"""VulnTell CNVD 适配器测试（阶段 5，Task 5.3）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from apps.vulntell.sources.cnvd import CNVDAdapter, CNVDConfig
from apps.vulntell.sources.errors import SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRequest


def _make_request(**kwargs) -> SourceRequest:
    now = datetime.now(timezone.utc)
    defaults = {
        "source": "cnvd",
        "dataset_id": "test",
        "dataset_version": "1.0",
        "window_start": now - timedelta(days=30),
        "window_end": now,
        "page_size": 20,
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


def test_cnvd_adapter_basic():
    """基本功能：返回正确记录。"""
    response = {
        "total": 2,
        "records": [
            {"cnvdId": "CNVD-2024-0001", "title": "Test Vulnerability 1"},
            {"cnvdId": "CNVD-2024-0002", "title": "Test Vulnerability 2"},
        ],
    }
    transport = MockTransport(response)
    adapter = CNVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 2
    assert result.source == "cnvd"
    assert not result.has_more


def test_cnvd_adapter_pagination():
    """分页：has_more 和 next_cursor。"""
    response = {
        "total": 50,
        "records": [
            {"cnvdId": f"CNVD-2024-{i:04d}", "title": f"Vulnerability {i}"}
            for i in range(20)
        ],
    }
    transport = MockTransport(response)
    adapter = CNVDAdapter(transport=transport)
    req = _make_request(page_size=20)

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 20
    assert result.has_more
    assert result.next_cursor == "2"


def test_cnvd_adapter_cursor():
    """游标：从指定页继续。"""
    response = {
        "total": 50,
        "records": [
            {"cnvdId": f"CNVD-2024-{i:04d}", "title": f"Vulnerability {i}"}
            for i in range(10)
        ],
    }
    transport = MockTransport(response)
    adapter = CNVDAdapter(transport=transport)
    req = _make_request(page_size=20)

    result = asyncio.run(adapter.fetch_page(req, cursor="2"))
    assert isinstance(result, SourcePage)
    assert result.record_count == 10
    # page 2 of 3 (total=50, page_size=20, total_pages=3)
    assert result.has_more  # page 2 < total_pages 3
    assert result.next_cursor == "3"


def test_cnvd_adapter_invalid_cursor():
    """无效游标：返回 invalid_response 错误。"""
    transport = MockTransport({})
    adapter = CNVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req, cursor="invalid"))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.INVALID_RESPONSE


def test_cnvd_adapter_rate_limit():
    """429 限流：返回 rate_limited 错误。"""
    transport = MockTransport({}, status_code=429)
    adapter = CNVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.RATE_LIMITED


def test_cnvd_adapter_timeout():
    """超时：返回 timeout 错误。"""
    async def timeout_transport(**kwargs):
        raise TimeoutError("Request timed out")

    adapter = CNVDAdapter(transport=timeout_transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.TIMEOUT


def test_cnvd_adapter_chinese_fields():
    """中文字段：正确保留中文内容。"""
    response = {
        "total": 1,
        "records": [
            {"cnvdId": "CNVD-2024-0001", "title": "测试漏洞"},
        ],
    }
    transport = MockTransport(response)
    adapter = CNVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.records[0].payload["title"] == "测试漏洞"


def test_cnvd_config_defaults():
    """配置默认值。"""
    config = CNVDConfig()
    assert "cnvd.org.cn" in config.endpoint
    assert config.page_size == 20
    assert config.timeout_seconds == 30.0
