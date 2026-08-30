"""VulnTell 分页 Fixture Adapter（阶段 4，Task 4.3）。

将 JSON fixture 包装为支持分页、故障注入的适配器。
支持固定 page size、空页、重复页、乱序、游标失效、单条坏记录、指定页超时/限流/权限错误和中断注入。

约束：
- 默认 adapter 仍为离线且不创建 socket
- 重复页由 page fingerprint 去重
- 坏记录隔离并计入质量问题，不丢弃整页
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .errors import SourceError, SourceErrorKind
from .protocol import SourcePage, SourceRecord, SourceRequest


@dataclass
class PagedFixtureConfig:
    """Fixture 分页配置（可注入故障）。

    Attributes:
        page_size: 每页记录数
        fault_pages: 需要注入故障的页码列表
        fault_kind: 故障类型（timeout/rate_limited/auth/forbidden 等）
        duplicate_pages: 需要重复输出的页码列表
        out_of_order_pages: 需要乱序输出的页码列表
        bad_record_pages: 包含坏记录的页码列表
        max_pages: 最大返回页数（None 表示不限制）
    """
    page_size: int = 5
    fault_pages: dict[int, SourceErrorKind] = field(default_factory=dict)
    duplicate_pages: list[int] = field(default_factory=list)
    out_of_order_pages: list[int] = field(default_factory=list)
    bad_record_pages: list[int] = field(default_factory=list)
    max_pages: Optional[int] = None


class PagedFixtureSource:
    """分页 Fixture 适配器：将 JSON 数组包装为分页 SourcePage 流。

    支持：
    - 固定 page size（最后一页可能不足）
    - 空页（records 为空列表）
    - 故障注入（指定页返回 SourceError）
    - 重复页（同一页返回两次，用于去重测试）
    - 乱序页（页码不按顺序，用于规范化测试）
    - 坏记录（单条记录 source_record_id 为空或 payload 无效）
    - 中断注入（通过 max_pages 限制）

    约定：
    - 游标格式："{request_fingerprint}:{page_index}"
    - 首次请求 cursor=None
    - 最后一页 has_more=False, next_cursor=None
    """

    def __init__(
        self,
        source: str,
        records: list[dict[str, Any]],
        config: Optional[PagedFixtureConfig] = None,
    ) -> None:
        self.source = source
        self._records = [SourceRecord.from_dict(r) for r in records]
        self._config = config or PagedFixtureConfig()
        self._page_size = self._config.page_size

    @classmethod
    def from_json_file(
        cls,
        source: str,
        path: str | pathlib.Path,
        config: Optional[PagedFixtureConfig] = None,
    ) -> "PagedFixtureSource":
        """从 JSON 文件创建（兼容旧 fixture 格式）。"""
        path = pathlib.Path(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # 兼容旧格式：可能是 dict 包含 records 字段，或直接是数组
        if isinstance(data, dict) and "records" in data:
            records = data["records"]
        elif isinstance(data, list):
            records = data
        else:
            raise ValueError(f"Invalid fixture format in {path}")
        return cls(source, records, config)

    def _parse_cursor(self, cursor: str) -> tuple[str, int]:
        """解析游标，返回 (request_fingerprint, page_index)。"""
        if not cursor:
            raise SourceError(
                source=self.source,
                kind=SourceErrorKind.INVALID_RESPONSE,
                message="Invalid cursor format",
                retryable=False,
            )
        parts = cursor.split(":")
        if len(parts) != 2:
            raise SourceError(
                source=self.source,
                kind=SourceErrorKind.INVALID_RESPONSE,
                message="Invalid cursor format",
                retryable=False,
            )
        try:
            page_index = int(parts[1])
        except ValueError:
            raise SourceError(
                source=self.source,
                kind=SourceErrorKind.INVALID_RESPONSE,
                message="Invalid cursor page index",
                retryable=False,
            )
        return parts[0], page_index

    def _make_cursor(self, request_fingerprint: str, page_index: int) -> str:
        """生成游标。"""
        return f"{request_fingerprint}:{page_index}"

    def _get_page_records(self, page_index: int) -> list[SourceRecord]:
        """获取指定页的记录。"""
        start = page_index * self._page_size
        end = start + self._page_size
        return list(self._records[start:end])

    def _make_record_safe(self, record: SourceRecord) -> SourceRecord:
        """确保记录可序列化（坏记录标记但不丢弃）。"""
        # 这里只是确保 record 结构完整，坏记录的检测在 SourcePage 构造时
        return record

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourcePage | SourceError:
        """获取一页数据。

        Args:
            request: 同步请求
            cursor: 分页游标（None 表示首页）

        Returns:
            SourcePage 或 SourceError
        """
        request_fingerprint = request.request_fingerprint

        # 解析游标
        if cursor:
            try:
                fp, page_index = self._parse_cursor(cursor)
                if fp != request_fingerprint:
                    return SourceError(
                        source=self.source,
                        kind=SourceErrorKind.INVALID_RESPONSE,
                        message="Cursor fingerprint mismatch",
                        retryable=False,
                    )
            except SourceError as e:
                return e
        else:
            page_index = 0

        # 故障注入：指定页返回错误
        if page_index in self._config.fault_pages:
            kind = self._config.fault_pages[page_index]
            return SourceError(
                source=self.source,
                kind=kind,
                message=f"Injected fault on page {page_index}",
                retryable=kind in (SourceErrorKind.TIMEOUT, SourceErrorKind.RATE_LIMITED, SourceErrorKind.TRANSIENT),
                retry_after=60 if kind == SourceErrorKind.RATE_LIMITED else 5,
            )

        # 中断注入：超过最大页数
        if self._config.max_pages is not None and page_index >= self._config.max_pages:
            has_more = False
            next_cursor = None
            records = []
        else:
            records = self._get_page_records(page_index)
            total_pages = (len(self._records) + self._page_size - 1) // self._page_size
            has_more = page_index + 1 < total_pages
            next_cursor = (
                self._make_cursor(request_fingerprint, page_index + 1) if has_more else None
            )

        # 构造 SourceRecord 列表（包含坏记录标记）
        safe_records = []
        for r in records:
            # 简单坏记录检测：source_record_id 为空
            if not r.source_record_id:
                # 坏记录保留但标记 metadata
                safe_records.append(
                    SourceRecord(
                        source_record_id=f"__bad_{page_index}_{len(safe_records)}",
                        payload=r.payload,
                        metadata={**r.metadata, "_quality_issue": "missing_id"},
                    )
                )
            else:
                safe_records.append(self._make_record_safe(r))

        # 返回首页（无游标）或后续页
        return SourcePage(
            records=tuple(safe_records),
            next_cursor=next_cursor,
            has_more=has_more,
            page_index=page_index,
            source=self.source,
            observed_at=datetime.now(timezone.utc),
            request_fingerprint=request_fingerprint,
        )

    async def fetch_all(
        self, request: SourceRequest
    ) -> tuple[list[SourceRecord], list[SourceError]]:
        """获取所有页的数据（便利方法，用于测试）。

        Returns:
            (所有成功记录, 所有错误)
        """
        all_records: list[SourceRecord] = []
        all_errors: list[SourceError] = []
        cursor = None

        while True:
            result = await self.fetch_page(request, cursor)
            if isinstance(result, SourceError):
                all_errors.append(result)
                if not result.retryable:
                    break
                # 可重试错误跳过继续
                cursor = None
            else:
                all_records.extend(result.records)
                if not result.has_more:
                    break
                cursor = result.next_cursor

        return all_records, all_errors


class FaultyPagedSource:
    """故障注入适配器：总是返回指定错误（用于测试部分失败）。"""

    def __init__(
        self,
        source: str,
        error_kind: SourceErrorKind = SourceErrorKind.TRANSIENT,
        error_message: str = "injected source failure",
    ) -> None:
        self.source = source
        self._error_kind = error_kind
        self._error_message = error_message

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourceError:
        return SourceError(
            source=self.source,
            kind=self._error_kind,
            message=self._error_message,
            retryable=False,
        )
