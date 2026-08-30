"""VulnTell 同步编排（阶段 4 收尾）。

SyncRunner 负责创建/恢复 SyncRun、循环 fetch_page、在"页面验证→规范化→持久化成功"
后提交游标 checkpoint，并在失败/取消时保存最后安全边界。

约束：
- 批次提交必须幂等，恢复只重放未确认页面
- 与现有 VulnTellJobRunner 组合，但不把分页循环塞入业务 Agent
- 不保存连接、响应正文或凭据
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apps.vulntell.domain.models import (
    SyncErrorSummary,
    SyncPageCheckpoint,
    SyncRun,
    SyncRunStatus,
    utc,
)
from apps.vulntell.sources.errors import SourceError
from apps.vulntell.sources.fixtures import PagedFixtureSource
from apps.vulntell.sources.protocol import SourcePage, SourceRequest


class SyncRunner:
    """同步运行器：管理分页循环、checkpoint 和幂等。

    约束：
    - 仅暴露 run/resume/cancel 方法
    - 不保存连接、响应正文或凭据
    - 批次提交使用 execution_key 幂等
    """

    def __init__(
        self,
        source_adapter: PagedFixtureSource,
        checkpoint_store: Optional[Any] = None,
        persist_fn: Optional[Callable] = None,
    ) -> None:
        self._source = source_adapter.source
        self._adapter = source_adapter
        self._checkpoint_store = checkpoint_store
        self._persist_fn = persist_fn or self._default_persist
        self._checkpoints: dict[str, SyncPageCheckpoint] = {}

    async def create_run(
        self,
        request: SourceRequest,
        run_id: Optional[str] = None,
        source_version: str = "",
        total_pages: int = 0,
    ) -> SyncRun:
        """创建新的同步运行。"""
        run_id = run_id or str(uuid.uuid4())

        # 计算 state_hash（确定性）
        state_hash_data = {
            "run_id": run_id,
            "source": request.source,
            "page_size": request.page_size,
            "request_fingerprint": request.request_fingerprint,
        }
        raw = json.dumps(state_hash_data, sort_keys=True)
        state_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]

        return SyncRun(
            run_id=run_id,
            source=request.source,
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            window_start=request.window_start,
            window_end=request.window_end,
            page_size=request.page_size,
            request_fingerprint=request.request_fingerprint,
            state_hash=state_hash,
            started_at=datetime.now(timezone.utc),
            status=SyncRunStatus.PENDING,
            source_version=source_version,
            total_pages=total_pages,
        )

    async def run(self, run: SyncRun, request: SourceRequest) -> SyncRun:
        """执行完整的同步流程（首页）。"""
        if not run.can_transition_to(SyncRunStatus.RUNNING):
            raise ValueError(f"Cannot start run in status {run.status}")

        run = run.transition_to(SyncRunStatus.RUNNING)
        return await self._execute_pages(run, request, start_cursor=None)

    async def resume(self, run: SyncRun, request: SourceRequest) -> SyncRun:
        """从最后成功游标恢复。"""
        if run.status not in (SyncRunStatus.PENDING, SyncRunStatus.PARTIAL):
            raise ValueError(f"Cannot resume run in status {run.status}")

        if run.status == SyncRunStatus.PENDING:
            run = run.transition_to(SyncRunStatus.RUNNING)
        else:
            # partial -> running
            run = run.transition_to(SyncRunStatus.RUNNING)

        return await self._execute_pages(run, request, start_cursor=run.last_success_cursor)

    async def cancel(self, run: SyncRun) -> SyncRun:
        """取消运行。"""
        if not run.can_transition_to(SyncRunStatus.CANCELLED):
            raise ValueError(f"Cannot cancel run in status {run.status}")
        return run.transition_to(SyncRunStatus.CANCELLED)

    async def _execute_pages(
        self, run: SyncRun, request: SourceRequest, start_cursor: Optional[str]
    ) -> SyncRun:
        """执行分页循环。"""
        cursor = start_cursor
        page_index = 0
        retry_count = 0
        max_retries = 3

        if start_cursor:
            # 从游标解析页码
            try:
                _, page_index = self._adapter._parse_cursor(start_cursor)
            except Exception:
                page_index = 0

        while True:
            # 检查是否已取消
            if run.status == SyncRunStatus.CANCELLED:
                return run

            # 获取一页
            result = await self._adapter.fetch_page(request, cursor)

            if isinstance(result, SourceError):
                # 错误处理
                run = await self._handle_error(run, result, page_index)
                if not result.retryable:
                    # 不可重试错误：根据当前状态决定最终状态
                    if run.status in (SyncRunStatus.RUNNING, SyncRunStatus.PARTIAL):
                        run = run.transition_to(SyncRunStatus.FAILED)
                    return run
                # 可重试错误：检查重试次数
                retry_count += 1
                if retry_count >= max_retries:
                    # 超过重试次数：根据当前状态决定最终状态
                    if run.status in (SyncRunStatus.RUNNING, SyncRunStatus.PARTIAL):
                        run = run.transition_to(SyncRunStatus.FAILED)
                    return run
                # 重试同一页
                continue

            # 重置重试计数
            retry_count = 0

            # 成功获取一页
            page = result

            # 首页：更新 total_pages（从页面流推断）
            if run.completed_pages == 0 and run.total_pages == 0:
                # 如果 page_index == 0 且 has_more，total_pages 需要后续计算
                # 这里先设为 -1 表示未知
                run = run.model_copy(update={"total_pages": -1})

            # 验证页面指纹（重复页检测）
            exec_key = run.execution_key(page.page_index)
            if not self._validate_page(exec_key, page):
                # 跳过重复页
                page_index += 1
                cursor = page.next_cursor
                continue

            # 持久化
            persisted = await self._persist_page(run, page)
            if not persisted:
                run = await self._handle_persist_error(run, page)
                continue

            # 更新状态
            run = self._update_run_after_success(run, page, exec_key)

            # 检查是否完成
            if not page.has_more:
                # 计算 total_pages
                if run.total_pages == -1:
                    # 从 page_index 推断 total_pages
                    run = run.model_copy(update={"total_pages": page.page_index + 1})

                # 检查是否所有页都完成
                if run.completed_pages >= run.total_pages:
                    run = run.transition_to(SyncRunStatus.SUCCEEDED)
                else:
                    run = run.transition_to(SyncRunStatus.PARTIAL)
                return run

            # 下一页
            cursor = page.next_cursor
            page_index += 1

    def _validate_page(self, exec_key: str, page: SourcePage) -> bool:
        """验证页面（重复页检测）。"""
        # 使用 execution_key 检查是否已处理过
        if exec_key in self._checkpoints:
            return False
        return True

    async def _persist_page(self, run: SyncRun, page: SourcePage) -> bool:
        """持久化页面（幂等）。"""
        exec_key = run.execution_key(page.page_index)
        try:
            # 检查是否已持久化
            existing = await self._load_checkpoint(exec_key)
            if existing and existing.persisted:
                return True

            # 调用持久化函数
            await self._persist_fn(run.source, page.records)

            # 更新 checkpoint
            checkpoint = SyncPageCheckpoint(
                page_index=page.page_index,
                page_fingerprint=page.page_fingerprint,
                record_count=page.record_count,
                persisted=True,
                persisted_at=datetime.now(timezone.utc),
            )
            await self._save_checkpoint_entry(exec_key, checkpoint)

            return True
        except Exception:
            return False

    async def _handle_error(self, run: SyncRun, error: SourceError, page_index: int) -> SyncRun:
        """处理错误。"""
        error_summary = SyncErrorSummary(
            source=error.source,
            kind=error.kind.value,
            count=1,
            last_message=error.message,
            retryable=error.retryable,
        )

        # 更新运行状态
        if run.status == SyncRunStatus.RUNNING:
            run = run.transition_to(SyncRunStatus.PARTIAL)

        # 保存错误到 checkpoint
        exec_key = run.execution_key(page_index)
        checkpoint = SyncPageCheckpoint(
            page_index=page_index,
            page_fingerprint="",
            record_count=0,
            persisted=False,
            error=error_summary,
        )
        await self._save_checkpoint_entry(exec_key, checkpoint)

        return run

    async def _handle_persist_error(self, run: SyncRun, page: SourcePage) -> SyncRun:
        """处理持久化错误。"""
        error_summary = SyncErrorSummary(
            source=run.source,
            kind="persist_failed",
            count=1,
            last_message="Failed to persist page",
            retryable=False,
        )
        return await self._handle_error(run, SourceError(
            source=run.source,
            kind="transient",
            message="Persist failed",
            retryable=False,
        ), page.page_index)

    def _update_run_after_success(self, run: SyncRun, page: SourcePage, exec_key: str) -> SyncRun:
        """更新运行状态（成功页）。"""
        updates = {
            "last_success_cursor": page.next_cursor or run.last_success_cursor,
            "completed_pages": run.completed_pages + 1,
            "total_records": run.total_records + page.record_count,
        }

        # 保存 checkpoint
        checkpoint = SyncPageCheckpoint(
            page_index=page.page_index,
            page_fingerprint=page.page_fingerprint,
            record_count=page.record_count,
            persisted=True,
            persisted_at=datetime.now(timezone.utc),
        )
        self._checkpoints[exec_key] = checkpoint

        return run.model_copy(update=updates)

    async def _load_checkpoint(self, exec_key: str) -> Optional[SyncPageCheckpoint]:
        """加载 checkpoint。"""
        return self._checkpoints.get(exec_key)

    async def _save_checkpoint_entry(self, exec_key: str, checkpoint: SyncPageCheckpoint) -> None:
        """保存 checkpoint 条目。"""
        self._checkpoints[exec_key] = checkpoint

    async def _default_persist(self, source: str, records) -> None:
        """默认持久化函数（no-op）。"""
        pass


class SyncRunnerService:
    """同步运行服务：组合 SyncRunner 和 checkpoint 持久化。"""

    def __init__(
        self,
        source_adapter: PagedFixtureSource,
        checkpoint_store: Optional[Any] = None,
        persist_fn: Optional[Callable] = None,
    ) -> None:
        self._runner = SyncRunner(source_adapter, checkpoint_store, persist_fn)
        self._runs: dict[str, SyncRun] = {}

    async def start_sync(
        self,
        request: SourceRequest,
        run_id: Optional[str] = None,
        total_pages: int = 0,
    ) -> SyncRun:
        """启动新的同步运行。"""
        run = await self._runner.create_run(request, run_id, total_pages=total_pages)
        self._runs[run.run_id] = run
        run = await self._runner.run(run, request)
        self._runs[run.run_id] = run
        return run

    async def resume_sync(self, run_id: str, request: SourceRequest) -> SyncRun:
        """恢复同步运行。"""
        run = self._runs.get(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        run = await self._runner.resume(run, request)
        self._runs[run.run_id] = run
        return run

    async def cancel_sync(self, run_id: str) -> SyncRun:
        """取消同步运行。"""
        run = self._runs.get(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        run = await self._runner.cancel(run)
        self._runs[run.run_id] = run
        return run

    def get_run(self, run_id: str) -> Optional[SyncRun]:
        """获取运行状态。"""
        return self._runs.get(run_id)
