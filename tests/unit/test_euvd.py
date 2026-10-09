"""VulnTell EUVD 适配器测试（阶段 6，Task 6.3；2026-09 按最新 ENISA EUVD API 重写）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from apps.vulntell.sources.euvd import EUVDAdapter, EUVDConfig
from apps.vulntell.sources.errors import SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRequest


def _make_request(**kwargs) -> SourceRequest:
    now = datetime.now(timezone.utc)
    defaults = {
        "source": "euvd",
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
        self.calls: list[dict] = []

    async def __call__(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {
            "status_code": self._status_code,
            "data": self._response if self._status_code == 200 else None,
            "error": "error" if self._status_code != 200 else None,
        }


def _make_item(euvd_id: str, **overrides) -> dict:
    item = {
        "id": euvd_id,
        "enisaUuid": "743ae9cb-2d27-31a4-8f31-5dfb14a86d9f",
        "description": "Test vulnerability",
        "datePublished": "Sep 10, 2024, 4:53:56 PM",
        "dateUpdated": "Sep 11, 2024, 8:00:00 AM",
        "baseScore": 8.8,
        "baseScoreVersion": "3.1",
        "baseScoreVector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
        "references": "https://example.com/advisory\n",
        "aliases": "CVE-2024-38225\nGHSA-pg6q-2w5f-8pw9\n",
        "assigner": "example",
        "epss": 1.36,
        "enisaIdProduct": [
            {
                "id": "p-1",
                "product": {"name": "Example Product", "vendor": {"name": "Example Vendor"}},
                "product_version": "1.0 <2.0",
            }
        ],
    }
    item.update(overrides)
    return item


def test_euvd_adapter_basic():
    """基本功能：返回正确记录。"""
    response = {
        "total": 2,
        "items": [
            _make_item("EUVD-2024-0001", aliases="CVE-2024-0001\n"),
            _make_item("EUVD-2024-0002", aliases="CVE-2024-0002\n"),
        ],
    }
    transport = MockTransport(response)
    adapter = EUVDAdapter(transport=transport)
    req = _make_request(
        window_start=datetime(2024, 9, 1, tzinfo=timezone.utc),
        window_end=datetime(2024, 10, 1, tzinfo=timezone.utc),
    )

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 2
    assert result.source == "euvd"
    assert not result.has_more

    # 验证请求参数：page 0 起、日期窗口、search 路径
    call = transport.calls[0]
    assert call["endpoint"].endswith("/search")
    assert call["params"]["page"] == 0
    assert call["params"]["fromDate"] == "2024-09-01"
    assert call["params"]["toDate"] == "2024-10-01"

    record = result.records[0]
    assert record.source_record_id == "EUVD-2024-0001"
    assert record.payload["cve_id"] == "CVE-2024-0001"
    assert record.payload["published_at"] == "2024-09-10T16:53:56+00:00"
    assert record.payload["cvss_score"] == 8.8
    assert record.payload["aliases"] == ["CVE-2024-0001"]


def test_euvd_adapter_pagination():
    """分页：has_more 和 next_cursor。"""
    response = {
        "total": 150,
        "items": [_make_item(f"EUVD-2024-{i:05d}") for i in range(100)],
    }
    transport = MockTransport(response)
    adapter = EUVDAdapter(transport=transport)
    req = _make_request(
        page_size=100,
        window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 100
    assert result.has_more
    assert result.next_cursor == "2"


def test_euvd_adapter_cursor():
    """游标：从指定页继续。"""
    response = {
        "total": 150,
        "items": [_make_item(f"EUVD-2024-{i:05d}") for i in range(50)],
    }
    transport = MockTransport(response)
    adapter = EUVDAdapter(transport=transport)
    req = _make_request(
        page_size=100,
        window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    result = asyncio.run(adapter.fetch_page(req, cursor="2"))
    assert isinstance(result, SourcePage)
    assert transport.calls[0]["params"]["page"] == 1
    assert result.record_count == 50
    assert not result.has_more


def test_euvd_adapter_window_filter():
    """窗口过滤：窗口外记录被丢弃（半开区间）。"""
    response = {
        "total": 3,
        "items": [
            _make_item("EUVD-2024-0001", datePublished="Aug 31, 2024, 11:59:59 PM"),
            _make_item("EUVD-2024-0002", datePublished="Sep 10, 2024, 12:00:00 AM"),
            _make_item("EUVD-2024-0003", datePublished="Oct 1, 2024, 12:00:00 AM"),
        ],
    }
    transport = MockTransport(response)
    adapter = EUVDAdapter(transport=transport)
    req = _make_request(
        window_start=datetime(2024, 9, 10, tzinfo=timezone.utc),
        window_end=datetime(2024, 10, 1, tzinfo=timezone.utc),
    )

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 1
    assert result.records[0].source_record_id == "EUVD-2024-0002"


def test_euvd_adapter_rate_limit():
    """429 限流：返回 rate_limited 错误。"""
    transport = MockTransport({}, status_code=429)
    adapter = EUVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.RATE_LIMITED


def test_euvd_adapter_timeout():
    """超时：返回 timeout 错误。"""
    async def timeout_transport(**kwargs):
        raise TimeoutError("Request timed out")

    adapter = EUVDAdapter(transport=timeout_transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.TIMEOUT


def test_euvd_adapter_empty_response():
    """空响应：返回空页。"""
    response = {"total": 0, "items": []}
    transport = MockTransport(response)
    adapter = EUVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 0
    assert not result.has_more


def test_euvd_config_defaults():
    """配置默认值。"""
    config = EUVDConfig()
    assert "euvdservices.enisa.europa.eu" in config.endpoint
    assert config.timeout_seconds == 30.0
    assert config.page_size == 100


def test_euvd_adapter_product_mapping():
    """产品与引用字段映射。"""
    response = {"total": 1, "items": [_make_item("EUVD-2024-0001")]}
    transport = MockTransport(response)
    adapter = EUVDAdapter(transport=transport)
    req = _make_request(
        window_start=datetime(2024, 9, 1, tzinfo=timezone.utc),
        window_end=datetime(2024, 10, 1, tzinfo=timezone.utc),
    )

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 1
    record = result.records[0]
    assert record.payload["affected"] == [
        {"vendor": "Example Vendor", "product": "Example Product", "versions": ["1.0 <2.0"]}
    ]
    assert record.payload["references"] == [
        {"type": "WEB", "url": "https://example.com/advisory"}
    ]
    assert record.payload["cvss_vector"] == "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H"
    assert record.payload["epss"] == 1.36
