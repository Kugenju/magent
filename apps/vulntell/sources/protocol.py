"""VulnTell 数据源协议（阶段 4，Task 4.1）。

定义不可变、可 JSON 序列化的同步请求、页面和游标协议。
阶段 4 冻结窗口/排序/指纹，为阶段 5 真实来源提供稳定边界。

约束：
- 游标（SyncCursor）是 opaque 字符串，大小上限 4KB
- 窗口边界含 start、不含 end（半开区间）
- 排序按 source_record_id 稳定升序
- request_fingerprint 由请求参数确定性生成，相同参数产生相同指纹
- 不包含任何凭据或敏感信息
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# 游标大小上限（字节）
CURSOR_MAX_BYTES = 4096

# 窗口边界类型
# start_inclusive=True 表示包含起始时间
# end_inclusive=False 表示不包含结束时间（半开区间 [start, end)）
WINDOW_START_INCLUSIVE = True
WINDOW_END_INCLUSIVE = False


@dataclass(frozen=True)
class SourceRequest:
    """数据源同步请求（不可变值对象）。

    Attributes:
        source: 来源标识符（如 "nvd", "cnvd"）
        dataset_id: 数据集 ID
        dataset_version: 数据集版本
        window_start: 同步窗口起始时间（含）
        window_end: 同步窗口结束时间（不含）
        page_size: 每页记录数（1-1000，默认 100）
        cursor: 游标，None 表示首次请求
        filters: 过滤条件（可选，如 cve_id 前缀）
    """
    source: str
    dataset_id: str
    dataset_version: str
    window_start: datetime
    window_end: datetime
    page_size: int = 100
    cursor: Optional[str] = None
    filters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not 1 <= self.page_size <= 1000:
            raise ValueError(f"page_size must be 1-1000, got {self.page_size}")
        if self.window_start >= self.window_end:
            raise ValueError(f"window_start must be before window_end")
        if self.cursor is not None and len(self.cursor.encode()) > CURSOR_MAX_BYTES:
            raise ValueError(f"cursor exceeds {CURSOR_MAX_BYTES} bytes")
        if not self.source:
            raise ValueError("source must not be empty")
        if not self.dataset_id:
            raise ValueError("dataset_id must not be empty")

    @property
    def request_fingerprint(self) -> str:
        """请求指纹：相同参数确定性生成相同值。

        指纹不包含 cursor（分页状态不影响请求语义）。
        """
        data = {
            "source": self.source,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "page_size": self.page_size,
            "filters": self.filters,
        }
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 字典。"""
        return {
            "source": self.source,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "page_size": self.page_size,
            "cursor": self.cursor,
            "filters": self.filters,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceRequest":
        """从字典反序列化。"""
        return cls(
            source=data["source"],
            dataset_id=data["dataset_id"],
            dataset_version=data["dataset_version"],
            window_start=datetime.fromisoformat(data["window_start"]),
            window_end=datetime.fromisoformat(data["window_end"]),
            page_size=data.get("page_size", 100),
            cursor=data.get("cursor"),
            filters=data.get("filters", {}),
        )


@dataclass(frozen=True)
class SourceRecord:
    """数据源单条记录（分页输出的最小单元）。

    Attributes:
        source_record_id: 来源记录唯一 ID
        payload: 原始载荷（可能是 dict 或序列化字符串）
        metadata: 元数据（如发布时间、最后修改时间）
    """
    source_record_id: str
    payload: Any
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_record_id": self.source_record_id,
            "payload": self.payload,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceRecord":
        return cls(
            source_record_id=data["source_record_id"],
            payload=data["payload"],
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class SourcePage:
    """数据源分页结果（不可变值对象）。

    Attributes:
        records: 本页记录列表
        next_cursor: 下一页游标，None 表示无更多页
        has_more: 是否有更多页
        page_index: 页码（0-based）
        source: 来源标识符
        observed_at: 观测时间戳
        request_fingerprint: 对应请求的指纹
    """
    records: tuple[SourceRecord, ...]
    next_cursor: Optional[str]
    has_more: bool
    page_index: int
    source: str
    observed_at: datetime
    request_fingerprint: str

    def __post_init__(self):
        if self.page_index < 0:
            raise ValueError(f"page_index must be >= 0, got {self.page_index}")
        if not self.has_more and self.next_cursor is not None:
            raise ValueError("next_cursor must be None when has_more is False")
        if self.has_more and self.next_cursor is None:
            raise ValueError("next_cursor must not be None when has_more is True")

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def page_fingerprint(self) -> str:
        """页面指纹：用于重复页检测。"""
        data = {
            "source": self.source,
            "page_index": self.page_index,
            "request_fingerprint": self.request_fingerprint,
            "record_count": self.record_count,
            "record_ids": [r.source_record_id for r in self.records],
        }
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
            "page_index": self.page_index,
            "source": self.source,
            "observed_at": self.observed_at.isoformat(),
            "request_fingerprint": self.request_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourcePage":
        return cls(
            records=tuple(SourceRecord.from_dict(r) for r in data["records"]),
            next_cursor=data["next_cursor"],
            has_more=data["has_more"],
            page_index=data["page_index"],
            source=data["source"],
            observed_at=datetime.fromisoformat(data["observed_at"]),
            request_fingerprint=data["request_fingerprint"],
        )
