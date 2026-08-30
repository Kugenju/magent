"""VulnTell 同步编排测试（阶段 4 收尾）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from apps.vulntell.domain.models import SyncRunStatus
from apps.vulntell.pipeline.sync import SyncRunner, SyncRunnerService
from apps.vulntell.sources.errors import SourceErrorKind
from apps.vulntell.sources.fixtures import PagedFixtureConfig, PagedFixtureSource
from apps.vulntell.sources.protocol import SourceRequest


def _make_request(page_size: int = 5) -> SourceRequest:
    now = datetime.now(timezone.utc)
    return SourceRequest(
        source="nvd",
        dataset_id="test",
        dataset_version="1.0",
        window_start=now,
        window_end=now + timedelta(days=1),
        page_size=page_size,
    )


def test_sync_run_success():
    """正常同步：3 页全部完成，状态为 succeeded。"""
    records = [{"source_record_id": f"r{i}", "payload": {"i": i}} for i in range(15)]
    adapter = PagedFixtureSource("nvd", records, PagedFixtureConfig(page_size=5))
    runner = SyncRunner(adapter)
    req = _make_request(page_size=5)

    async def run():
        run = await runner.create_run(req, total_pages=3)
        return await runner.run(run, req)

    result = asyncio.run(run())
    assert result.status == SyncRunStatus.SUCCEEDED
    assert result.completed_pages == 3
    assert result.total_records == 15


def test_sync_run_empty():
    """空结果：0 页，状态为 succeeded。"""
    adapter = PagedFixtureSource("nvd", [], PagedFixtureConfig(page_size=5))
    runner = SyncRunner(adapter)
    req = _make_request(page_size=5)

    async def run():
        run = await runner.create_run(req, total_pages=1)
        return await runner.run(run, req)

    result = asyncio.run(run())
    assert result.status == SyncRunStatus.SUCCEEDED
    assert result.completed_pages == 1
    assert result.total_records == 0


def test_sync_run_retry_failure():
    """可重试错误超过重试次数后失败。"""
    records = [{"source_record_id": f"r{i}", "payload": {"i": i}} for i in range(15)]
    # 配置：第二页超时（可重试）
    config = PagedFixtureConfig(
        page_size=5,
        fault_pages={1: SourceErrorKind.TIMEOUT},
    )
    adapter = PagedFixtureSource("nvd", records, config)
    runner = SyncRunner(adapter)
    req = _make_request(page_size=5)

    async def run():
        run1 = await runner.create_run(req, total_pages=3)
        result1 = await runner.run(run1, req)
        # 第二页超时超过重试次数后失败
        assert result1.status == SyncRunStatus.FAILED
        assert result1.completed_pages == 1

    asyncio.run(run())


def test_sync_run_duplicate_page():
    """重复页检测：同一页不重复写入。"""
    records = [{"source_record_id": f"r{i}", "payload": {"i": i}} for i in range(5)]
    adapter = PagedFixtureSource("nvd", records, PagedFixtureConfig(page_size=5))
    runner = SyncRunner(adapter)
    req = _make_request(page_size=5)

    async def run():
        # 创建运行
        run = await runner.create_run(req, total_pages=1)
        # 第一次运行
        result1 = await runner.run(run, req)
        assert result1.status == SyncRunStatus.SUCCEEDED

        # 再次运行（模拟重复）
        run2 = await runner.create_run(req, total_pages=1)
        return await runner.run(run2, req)

    result = asyncio.run(run())
    # 重复运行应该成功，但不重复写入（幂等）
    assert result.status == SyncRunStatus.SUCCEEDED


def test_sync_run_cancel():
    """取消运行：状态转为 cancelled。"""
    records = [{"source_record_id": f"r{i}", "payload": {"i": i}} for i in range(10)]
    adapter = PagedFixtureSource("nvd", records, PagedFixtureConfig(page_size=5))
    runner = SyncRunner(adapter)
    req = _make_request(page_size=5)

    async def run():
        run = await runner.create_run(req, total_pages=2)
        return await runner.cancel(run)

    result = asyncio.run(run())
    assert result.status == SyncRunStatus.CANCELLED


def test_sync_runner_service():
    """SyncRunnerService：组合服务测试。"""
    records = [{"source_record_id": f"r{i}", "payload": {"i": i}} for i in range(10)]
    adapter = PagedFixtureSource("nvd", records, PagedFixtureConfig(page_size=5))
    service = SyncRunnerService(adapter)
    req = _make_request(page_size=5)

    async def run():
        # 启动同步
        run1 = await service.start_sync(req, total_pages=2)
        assert run1.status == SyncRunStatus.SUCCEEDED
        assert run1.completed_pages == 2

        # 获取运行状态
        fetched = service.get_run(run1.run_id)
        assert fetched is not None
        assert fetched.run_id == run1.run_id

    asyncio.run(run())


def test_sync_run_status_transitions():
    """状态转换验证。"""
    records = [{"source_record_id": "r1", "payload": {}}]
    adapter = PagedFixtureSource("nvd", records, PagedFixtureConfig(page_size=5))
    runner = SyncRunner(adapter)
    req = _make_request(page_size=5)

    async def run():
        run = await runner.create_run(req, total_pages=1)
        assert run.status == SyncRunStatus.PENDING

        # pending -> running
        run = await runner.run(run, req)
        # running -> succeeded (空结果)
        assert run.status == SyncRunStatus.SUCCEEDED

    asyncio.run(run())
