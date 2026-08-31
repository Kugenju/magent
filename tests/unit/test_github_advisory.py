"""VulnTell GitHub Advisory Database 适配器测试（阶段 6，Task 6.2）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from apps.vulntell.sources.github_advisory import GitHubAdvisoryAdapter, GitHubAdvisoryConfig
from apps.vulntell.sources.errors import SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRequest


def _make_request(**kwargs) -> SourceRequest:
    now = datetime.now(timezone.utc)
    defaults = {
        "source": "github_advisory",
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


def test_github_advisory_adapter_basic():
    """基本功能：返回正确记录。"""
    response = [
        {
            "ghsa_id": "GHSA-2024-0001",
            "cve_id": "CVE-2024-0001",
            "summary": "Test vulnerability 1",
            "severity": "high",
            "published_at": "2024-01-01T00:00:00Z",
        },
        {
            "ghsa_id": "GHSA-2024-0002",
            "cve_id": None,
            "summary": "Test vulnerability 2",
            "severity": "medium",
            "published_at": "2024-01-02T00:00:00Z",
        },
    ]
    transport = MockTransport(response)
    adapter = GitHubAdvisoryAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 2
    assert result.source == "github_advisory"
    assert not result.has_more


def test_github_advisory_adapter_pagination():
    """分页：has_more 和 next_cursor。"""
    response = [
        {
            "ghsa_id": f"GHSA-2024-{i:04d}",
            "cve_id": f"CVE-2024-{i:04d}",
            "summary": f"Vulnerability {i}",
        }
        for i in range(100)
    ]
    transport = MockTransport(response)
    adapter = GitHubAdvisoryAdapter(transport=transport)
    req = _make_request(page_size=100)

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 100
    assert result.has_more
    assert result.next_cursor == "2"


def test_github_advisory_adapter_cursor():
    """游标：从指定页继续。"""
    response = [
        {
            "ghsa_id": f"GHSA-2024-{i:04d}",
            "cve_id": f"CVE-2024-{i:04d}",
            "summary": f"Vulnerability {i}",
        }
        for i in range(50)
    ]
    transport = MockTransport(response)
    adapter = GitHubAdvisoryAdapter(transport=transport)
    req = _make_request(page_size=100)

    result = asyncio.run(adapter.fetch_page(req, cursor="2"))
    assert isinstance(result, SourcePage)
    assert result.record_count == 50
    assert not result.has_more


def test_github_advisory_adapter_rate_limit():
    """429 限流：返回 rate_limited 错误。"""
    transport = MockTransport({}, status_code=429)
    adapter = GitHubAdvisoryAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.RATE_LIMITED


def test_github_advisory_adapter_timeout():
    """超时：返回 timeout 错误。"""
    async def timeout_transport(**kwargs):
        raise TimeoutError("Request timed out")

    adapter = GitHubAdvisoryAdapter(transport=timeout_transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.TIMEOUT


def test_github_advisory_adapter_empty_response():
    """空响应：返回空页。"""
    response = []
    transport = MockTransport(response)
    adapter = GitHubAdvisoryAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 0
    assert not result.has_more


def test_github_advisory_config_defaults():
    """配置默认值。"""
    config = GitHubAdvisoryConfig()
    assert "api.github.com" in config.endpoint
    assert config.timeout_seconds == 30.0
    assert config.page_size == 100


def test_github_advisory_adapter_aliases():
    """别名信息提取。"""
    response = [
        {
            "ghsa_id": "GHSA-2024-0001",
            "cve_id": "CVE-2024-0001",
            "summary": "Test vulnerability",
            "severity": "high",
        }
    ]
    transport = MockTransport(response)
    adapter = GitHubAdvisoryAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 1
    record = result.records[0]
    assert "CVE-2024-0001" in record.payload["aliases"]
    assert "GHSA-2024-0001" in record.payload["aliases"]
