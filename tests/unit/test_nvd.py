"""VulnTell NVD 适配器测试（阶段 5，Task 5.1，5C.2 扩展）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from apps.vulntell.sources.nvd import NVDAdapter, NVDConfig, NVDCursor, slice_time_window
from apps.vulntell.sources.errors import SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRequest


def _make_request(**kwargs) -> SourceRequest:
    now = datetime.now(timezone.utc)
    defaults = {
        "source": "nvd",
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
        self._calls = []

    async def __call__(self, **kwargs) -> dict:
        self._calls.append(kwargs)
        return {
            "status_code": self._status_code,
            "data": self._response if self._status_code == 200 else None,
            "error": "error" if self._status_code != 200 else None,
        }


def test_nvd_adapter_basic():
    """基本分页：返回正确记录。"""
    response = {
        "totalResults": 2,
        "vulnerabilities": [
            {"cve": {"id": "CVE-2024-0001", "published": "2024-01-01T00:00:00Z"}},
            {"cve": {"id": "CVE-2024-0002", "published": "2024-01-02T00:00:00Z"}},
        ],
    }
    transport = MockTransport(response)
    adapter = NVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 2
    assert result.source == "nvd"
    assert not result.has_more


def test_nvd_adapter_pagination():
    """分页：has_more 和 next_cursor。"""
    now = datetime.now(timezone.utc)
    response = {
        "totalResults": 150,
        "vulnerabilities": [
            {"cve": {"id": f"CVE-2024-{i:04d}"}}
            for i in range(100)
        ],
    }
    transport = MockTransport(response)
    adapter = NVDAdapter(transport=transport)
    req = _make_request(page_size=100)

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 100
    assert result.has_more
    # 验证游标格式
    cursor = NVDCursor.from_string(result.next_cursor)
    assert cursor.start_index == 100
    assert cursor.slice_index == 0


def test_nvd_adapter_cursor():
    """游标：从 startIndex 继续。"""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=30)
    window_end = now
    
    response = {
        "totalResults": 150,
        "vulnerabilities": [
            {"cve": {"id": f"CVE-2024-{i:04d}"}}
            for i in range(50)
        ],
    }
    transport = MockTransport(response)
    adapter = NVDAdapter(transport=transport)
    req = _make_request(page_size=100)

    # 创建游标
    cursor = NVDCursor(
        window_start=window_start,
        window_end=window_end,
        start_index=100,
        slice_index=0,
    )
    result = asyncio.run(adapter.fetch_page(req, cursor=cursor.to_string()))
    assert isinstance(result, SourcePage)
    assert result.record_count == 50
    assert not result.has_more


def test_nvd_adapter_rate_limit():
    """429 限流：返回 rate_limited 错误。"""
    transport = MockTransport({}, status_code=429)
    adapter = NVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.RATE_LIMITED
    assert result.retryable


def test_nvd_adapter_timeout():
    """超时：返回 timeout 错误。"""
    async def timeout_transport(**kwargs):
        raise TimeoutError("Request timed out")

    adapter = NVDAdapter(transport=timeout_transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.TIMEOUT


def test_nvd_adapter_auth_error():
    """401 认证错误：返回 auth 错误。"""
    transport = MockTransport({}, status_code=401)
    adapter = NVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.AUTH
    assert not result.retryable


def test_nvd_adapter_forbidden():
    """403 权限错误：返回 forbidden 错误。"""
    transport = MockTransport({}, status_code=403)
    adapter = NVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.FORBIDDEN


def test_nvd_adapter_not_found():
    """404 未找到：返回 not_found 错误。"""
    transport = MockTransport({}, status_code=404)
    adapter = NVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.NOT_FOUND


def test_nvd_adapter_server_error():
    """500 服务器错误：返回 transient 错误。"""
    transport = MockTransport({}, status_code=500)
    adapter = NVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.TRANSIENT
    assert result.retryable


def test_nvd_adapter_invalid_cursor():
    """无效游标：返回 invalid_response 错误。"""
    transport = MockTransport({})
    adapter = NVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req, cursor="invalid"))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.INVALID_RESPONSE


def test_nvd_adapter_empty_response():
    """空响应：返回空页。"""
    response = {"totalResults": 0, "vulnerabilities": []}
    transport = MockTransport(response)
    adapter = NVDAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 0
    assert not result.has_more


def test_nvd_config_defaults():
    """配置默认值。"""
    config = NVDConfig()
    assert config.endpoint == "https://services.nvd.nist.gov/rest/json/cves/2.0"
    assert config.page_size == 2000
    assert config.timeout_seconds == 30.0
    assert config.api_key is None
    assert config.max_window_days == 120


def test_nvd_cursor_serialization():
    """NVDCursor 序列化和反序列化。"""
    now = datetime.now(timezone.utc)
    cursor = NVDCursor(
        window_start=now - timedelta(days=30),
        window_end=now,
        start_index=100,
        slice_index=2,
    )
    cursor_str = cursor.to_string()
    restored = NVDCursor.from_string(cursor_str)
    assert restored.window_start == cursor.window_start
    assert restored.window_end == cursor.window_end
    assert restored.start_index == cursor.start_index
    assert restored.slice_index == cursor.slice_index


def test_nvd_time_window_slicing():
    """时间窗口分片。"""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=300)
    window_end = now
    
    slices = slice_time_window(window_start, window_end, max_days=120)
    assert len(slices) == 3  # 300 / 120 = 2.5, 需要 3 个分片
    
    # 验证分片连续性
    for i in range(len(slices) - 1):
        assert slices[i][1] == slices[i + 1][0]
    
    # 验证最后一个分片结束于 window_end
    assert slices[-1][1] == window_end
