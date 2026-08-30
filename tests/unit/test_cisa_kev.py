"""VulnTell CISA KEV 适配器测试（阶段 5，Task 5.2）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from apps.vulntell.sources.cisa_kev import CISAKEVAdapter, CISAKEVConfig
from apps.vulntell.sources.errors import SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRequest


def _make_request(**kwargs) -> SourceRequest:
    now = datetime.now(timezone.utc)
    defaults = {
        "source": "cisa_kev",
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


def test_cisa_kev_adapter_basic():
    """基本功能：返回正确记录。"""
    response = {
        "catalogVersion": "2024.01.01",
        "vulnerabilities": [
            {"cveID": "CVE-2024-0001", "vendorProject": "Test", "product": "Test"},
            {"cveID": "CVE-2024-0002", "vendorProject": "Test", "product": "Test"},
        ],
    }
    transport = MockTransport(response)
    adapter = CISAKEVAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 2
    assert result.source == "cisa_kev"
    assert not result.has_more


def test_cisa_kev_adapter_version_change():
    """版本变化检测：相同版本返回空记录。"""
    response = {
        "catalogVersion": "2024.02.01",
        "vulnerabilities": [
            {"cveID": "CVE-2024-0003", "vendorProject": "Test", "product": "Test"},
        ],
    }
    transport = MockTransport(response)
    adapter = CISAKEVAdapter(transport=transport)
    req = _make_request()

    # 首次同步
    result1 = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result1, SourcePage)
    assert result1.record_count == 1

    # 同版本再次同步（使用版本游标）
    result2 = asyncio.run(adapter.fetch_page(req, cursor="version:2024.02.01"))
    assert isinstance(result2, SourcePage)
    assert result2.record_count == 0  # 版本未变化


def test_cisa_kev_adapter_empty_catalog():
    """空 catalog：返回空页。"""
    response = {"catalogVersion": "2024.01.01", "vulnerabilities": []}
    transport = MockTransport(response)
    adapter = CISAKEVAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 0


def test_cisa_kev_adapter_invalid_cursor():
    """无效游标：返回 invalid_response 错误。"""
    transport = MockTransport({})
    adapter = CISAKEVAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req, cursor="invalid"))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.INVALID_RESPONSE


def test_cisa_kev_adapter_rate_limit():
    """429 限流：返回 rate_limited 错误。"""
    transport = MockTransport({}, status_code=429)
    adapter = CISAKEVAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.RATE_LIMITED


def test_cisa_kev_adapter_timeout():
    """超时：返回 timeout 错误。"""
    async def timeout_transport(**kwargs):
        raise TimeoutError("Request timed out")

    adapter = CISAKEVAdapter(transport=timeout_transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.TIMEOUT


def test_cisa_kev_config_defaults():
    """配置默认值。"""
    config = CISAKEVConfig()
    assert "cisa.gov" in config.endpoint
    assert config.timeout_seconds == 60.0
