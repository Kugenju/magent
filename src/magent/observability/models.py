"""阶段 8 观测数据模型（Task 1）。

纯数据模型，不依赖存储后端、OpenTelemetry SDK 或云服务。一个完整 run 对应一个
``Trace``；一次节点 attempt 对应一个 ``Span``；重试产生独立 attempt Span，通过相同
node 标识与明确 attempt 序号关联。

约束（见 docs/phases/PHASE8.md §4）：
- ``run_id`` / ``trace_id`` / workflow、node 版本在同一次执行中保持一致；
- 恢复运行必须保留原 run 关联（``resumed`` / ``resumed_from_seq`` / ``replayed_nodes``）；
- metadata 经过脱敏并限制大小、层级与集合长度；禁止写入 API Key、完整原始漏洞描述、
  未经验证的远程响应和大块 State；
- ``resource_samples`` 未采集时为 ``None`` 而不是 0。
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from enum import Enum
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field

_UTC = dt.timezone.utc

# 脱敏默认命中字段（大小写不敏感子串匹配）
DEFAULT_REDACT_FIELDS = frozenset(
    {
        "key",
        "token",
        "secret",
        "password",
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "credential",
        "credentials",
        "private_key",
    }
)


class SpanStatus(str, Enum):
    """Span 终态，覆盖成功/跳过/失败/超时/取消/未执行。"""

    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    NOT_EXECUTED = "not_executed"


def _dt(ts: float | None) -> dt.datetime | None:
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(ts, tz=_UTC)


class Trace(BaseModel):
    """一次完整 run 的观测根记录。"""

    trace_id: str
    run_id: str
    workflow_id: str
    workflow_version: str
    state_schema_version: str
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    status: str  # success | partial | failed | cancelled
    metadata: dict[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    """一次节点 attempt 的观测记录。"""

    span_id: str
    trace_id: str
    parent_span_id: str | None = None
    node_id: str
    agent_name: str
    attempt: int = 1
    queued_ms: float = 0.0
    duration_ms: float = 0.0
    status: SpanStatus
    error_type: str | None = None
    retry_reason: str | None = None
    cancellation_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    """一次 run 的聚合摘要，与 ExecutionReport / Checkpoint 对齐。"""

    trace_id: str
    run_id: str
    node_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    cancelled_count: int = 0
    skipped_count: int = 0
    not_executed_count: int = 0
    retry_count: int = 0
    timeout_count: int = 0
    peak_concurrency: int = 0
    checkpoint_writes: int = 0
    recovery_count: int = 0
    replayed_nodes: list[str] = Field(default_factory=list)
    duration_ms: float | None = None
    resource_samples: dict | None = None  # 未采集时为 None，不是 0


def redact(
    value: Any,
    *,
    max_str: int = 4096,
    max_keys: int = 64,
    max_items: int = 256,
    max_depth: int = 6,
    redact_fields: Iterable[str] = DEFAULT_REDACT_FIELDS,
) -> Any:
    """递归脱敏与有界化：截断长字符串、限制集合长度与嵌套深度、隐藏敏感键。"""
    fields = {f.lower() for f in redact_fields}
    return _redact(value, max_str, max_keys, max_items, max_depth, fields, 0)


def _redact(value, max_str, max_keys, max_items, max_depth, fields, depth):
    if isinstance(value, str):
        return value if len(value) <= max_str else value[:max_str] + "...<truncated>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        if depth >= max_depth:
            return "<nested>"  # 超过深度直接裁剪，避免大块 State 泄露
        out: dict = {}
        items = list(value.items())[:max_keys]
        for k, v in items:
            key_str = str(k).lower()
            if any(f in key_str for f in fields):
                out[k] = "<redacted>"
            else:
                out[k] = _redact(v, max_str, max_keys, max_items, max_depth, fields, depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        if depth >= max_depth:
            return ["<nested>"]
        return [
            _redact(v, max_str, max_keys, max_items, max_depth, fields, depth + 1)
            for v in list(value)[:max_items]
        ]
    # 其它类型直接字符串化并截断
    return str(value)[:max_str]


def redact_metadata(metadata: dict, **kw) -> dict:
    """对 metadata 做默认脱敏，返回新字典。"""
    return redact(metadata, **kw)


def to_jsonl(records: Iterable[BaseModel]) -> str:
    """逐条序列化（Trace/Span）为 JSONL 文本。"""
    return "\n".join(r.model_dump_json() for r in records) + ("\n" if list(records) else "")


def write_jsonl(path: str, records: Iterable[BaseModel]) -> None:
    import pathlib

    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_jsonl(records), encoding="utf-8")


def write_json(path: str, obj: BaseModel) -> None:
    import pathlib

    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj.model_dump_json(indent=2), encoding="utf-8")


def _new_id() -> str:
    return uuid.uuid4().hex
