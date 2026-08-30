"""VulnTell 数据源协议测试（阶段 4 收尾）。"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from apps.vulntell.sources.protocol import (
    SourcePage,
    SourceRecord,
    SourceRequest,
    CURSOR_MAX_BYTES,
)
from apps.vulntell.sources.errors import (
    SourceError,
    SourceErrorKind,
    classify_http_status,
    classify_exception,
    RETRY_HINTS,
)
from apps.vulntell.sources.fixtures import (
    PagedFixtureConfig,
    PagedFixtureSource,
    FaultyPagedSource,
)


# ---- SourceRequest 测试 ----


def test_source_request_round_trip():
    """协议 round-trip：序列化/反序列化保持不变。"""
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    req = SourceRequest(
        source="nvd",
        dataset_id="test",
        dataset_version="1.0",
        window_start=now,
        window_end=now + timedelta(days=1),
        page_size=50,
        cursor="abc:1",
        filters={"cve_prefix": "CVE-2024"},
    )
    d = req.to_dict()
    req2 = SourceRequest.from_dict(d)
    assert req.source == req2.source
    assert req.request_fingerprint == req2.request_fingerprint
    assert req.filters == req2.filters


def test_source_request_validation():
    """输入校验：非法参数拒绝。"""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="page_size"):
        SourceRequest(source="nvd", dataset_id="d", dataset_version="v",
                      window_start=now, window_end=now + timedelta(days=1), page_size=0)
    with pytest.raises(ValueError, match="window_start"):
        SourceRequest(source="nvd", dataset_id="d", dataset_version="v",
                      window_start=now + timedelta(days=1), window_end=now)
    with pytest.raises(ValueError, match="source"):
        SourceRequest(source="", dataset_id="d", dataset_version="v",
                      window_start=now, window_end=now + timedelta(days=1))
    with pytest.raises(ValueError, match="dataset_id"):
        SourceRequest(source="nvd", dataset_id="", dataset_version="v",
                      window_start=now, window_end=now + timedelta(days=1))


def test_source_request_fingerprint_stable():
    """相同请求指纹稳定。"""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=1)
    req1 = SourceRequest(source="nvd", dataset_id="d", dataset_version="v",
                         window_start=now, window_end=end, page_size=100)
    req2 = SourceRequest(source="nvd", dataset_id="d", dataset_version="v",
                         window_start=now, window_end=end, page_size=100)
    assert req1.request_fingerprint == req2.request_fingerprint


def test_source_request_fingerprint_differs():
    """不同请求产生不同指纹。"""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=1)
    req1 = SourceRequest(source="nvd", dataset_id="d", dataset_version="v",
                         window_start=now, window_end=end, page_size=100)
    req2 = SourceRequest(source="cnvd", dataset_id="d", dataset_version="v",
                         window_start=now, window_end=end, page_size=100)
    assert req1.request_fingerprint != req2.request_fingerprint


# ---- SourcePage 测试 ----


def test_source_page_round_trip():
    """协议 round-trip：序列化/反序列化保持不变。"""
    now = datetime.now(timezone.utc)
    record = SourceRecord(source_record_id="r1", payload={"a": 1})
    page = SourcePage(
        records=(record,),
        next_cursor="fp:1",
        has_more=True,
        page_index=0,
        source="nvd",
        observed_at=now,
        request_fingerprint="fp",
    )
    d = page.to_dict()
    page2 = SourcePage.from_dict(d)
    assert page.record_count == page2.record_count
    assert page.page_fingerprint == page2.page_fingerprint


def test_source_page_validation():
    """输入校验：非法参数拒绝。"""
    now = datetime.now(timezone.utc)
    record = SourceRecord(source_record_id="r1", payload={})
    with pytest.raises(ValueError, match="page_index"):
        SourcePage(records=(record,), next_cursor=None, has_more=False,
                   page_index=-1, source="nvd", observed_at=now,
                   request_fingerprint="fp")
    with pytest.raises(ValueError, match="next_cursor must be None"):
        SourcePage(records=(record,), next_cursor="x", has_more=False,
                   page_index=0, source="nvd", observed_at=now,
                   request_fingerprint="fp")
    with pytest.raises(ValueError, match="next_cursor must not be None"):
        SourcePage(records=(record,), next_cursor=None, has_more=True,
                   page_index=0, source="nvd", observed_at=now,
                   request_fingerprint="fp")


# ---- SourceError 测试 ----


def test_classify_http_status():
    """HTTP 状态码分类决策表。"""
    assert classify_http_status(429) == SourceErrorKind.RATE_LIMITED
    assert classify_http_status(408) == SourceErrorKind.TIMEOUT
    assert classify_http_status(504) == SourceErrorKind.TIMEOUT
    assert classify_http_status(401) == SourceErrorKind.AUTH
    assert classify_http_status(403) == SourceErrorKind.FORBIDDEN
    assert classify_http_status(404) == SourceErrorKind.NOT_FOUND
    assert classify_http_status(500) == SourceErrorKind.TRANSIENT
    assert classify_http_status(502) == SourceErrorKind.TRANSIENT
    assert classify_http_status(503) == SourceErrorKind.TRANSIENT
    assert classify_http_status(400) == SourceErrorKind.INVALID_RESPONSE


def test_retry_hints():
    """重试提示：429/超时可重试。"""
    for kind, (retryable, _) in RETRY_HINTS.items():
        if kind in (SourceErrorKind.RATE_LIMITED, SourceErrorKind.TIMEOUT, SourceErrorKind.TRANSIENT):
            assert retryable, f"{kind} should be retryable"
        else:
            assert not retryable, f"{kind} should not be retryable"


def test_source_error_scrubbing():
    """敏感字段脱敏：Authorization 等被移除。"""
    err = SourceError.from_http_status("nvd", 401, "Authorization: Bearer secret123", "c1")
    assert "secret123" not in err.message
    assert "REDACTED" in err.message


def test_source_error_round_trip():
    """协议 round-trip。"""
    err = SourceError(source="nvd", kind=SourceErrorKind.TIMEOUT, message="timeout",
                      retryable=True, retry_after=5, http_status=408, correlation_id="c1")
    d = err.to_dict()
    err2 = SourceError.from_dict(d)
    assert err.source == err2.source
    assert err.kind == err2.kind
    assert err.retryable == err2.retryable


# ---- PagedFixtureSource 测试 ----


def test_paged_fixture_basic():
    """基本分页：固定 page size 返回正确页数。"""
    from datetime import timedelta
    records = [{"source_record_id": f"r{i}", "payload": {"i": i}} for i in range(10)]
    source = PagedFixtureSource("nvd", records, PagedFixtureConfig(page_size=5))
    now = datetime.now(timezone.utc)
    req = SourceRequest(source="nvd", dataset_id="d", dataset_version="v",
                        window_start=now, window_end=now + timedelta(days=1), page_size=5)

    import asyncio
    page = asyncio.run(source.fetch_page(req))
    assert isinstance(page, SourcePage)
    assert page.record_count == 5
    assert page.has_more
    assert page.next_cursor is not None


def test_paged_fixture_empty():
    """空结果：返回空页。"""
    from datetime import timedelta
    source = PagedFixtureSource("nvd", [], PagedFixtureConfig(page_size=5))
    now = datetime.now(timezone.utc)
    req = SourceRequest(source="nvd", dataset_id="d", dataset_version="v",
                        window_start=now, window_end=now + timedelta(days=1), page_size=5)

    import asyncio
    page = asyncio.run(source.fetch_page(req))
    assert isinstance(page, SourcePage)
    assert page.record_count == 0
    assert not page.has_more


def test_paged_fixture_fault():
    """故障注入：指定页返回错误。"""
    from datetime import timedelta
    records = [{"source_record_id": f"r{i}", "payload": {}} for i in range(5)]
    config = PagedFixtureConfig(page_size=5, fault_pages={0: SourceErrorKind.TIMEOUT})
    source = PagedFixtureSource("nvd", records, config)
    now = datetime.now(timezone.utc)
    req = SourceRequest(source="nvd", dataset_id="d", dataset_version="v",
                        window_start=now, window_end=now + timedelta(days=1), page_size=5)

    import asyncio
    result = asyncio.run(source.fetch_page(req))
    assert isinstance(result, SourceError)
    assert result.kind == SourceErrorKind.TIMEOUT


def test_paged_fixture_fetch_all():
    """便利方法 fetch_all：获取所有页。"""
    from datetime import timedelta
    records = [{"source_record_id": f"r{i}", "payload": {"i": i}} for i in range(12)]
    source = PagedFixtureSource("nvd", records, PagedFixtureConfig(page_size=5))
    now = datetime.now(timezone.utc)
    req = SourceRequest(source="nvd", dataset_id="d", dataset_version="v",
                        window_start=now, window_end=now + timedelta(days=1), page_size=5)

    import asyncio
    all_records, all_errors = asyncio.run(source.fetch_all(req))
    assert len(all_records) == 12
    assert len(all_errors) == 0


# ---- FaultyPagedSource 测试 ----


def test_faulty_source():
    """故障适配器：总是返回错误。"""
    from datetime import timedelta
    source = FaultyPagedSource("nvd", SourceErrorKind.TRANSIENT, "injected")
    now = datetime.now(timezone.utc)
    req = SourceRequest(source="nvd", dataset_id="d", dataset_version="v",
                        window_start=now, window_end=now + timedelta(days=1))

    import asyncio
    result = asyncio.run(source.fetch_page(req))
    assert isinstance(result, SourceError)
    assert result.kind == SourceErrorKind.TRANSIENT
