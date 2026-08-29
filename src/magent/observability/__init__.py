"""magent 阶段 8 观测能力。

纯数据模型（``Trace`` / ``Span`` / ``RunSummary``）与只读记录器
（``build_observability`` / ``TraceCollector``）。记录器只消费 ExecutionReport、
Checkpoint 历史与可选 EventBus，不修改执行语义。
"""

from __future__ import annotations

from .models import (
    RunSummary,
    Span,
    SpanStatus,
    Trace,
    redact,
    redact_metadata,
    to_jsonl,
    write_json,
    write_jsonl,
)
from .recorder import TraceCollector, build_observability

__all__ = [
    "Trace",
    "Span",
    "SpanStatus",
    "RunSummary",
    "redact",
    "redact_metadata",
    "to_jsonl",
    "write_json",
    "write_jsonl",
    "build_observability",
    "TraceCollector",
]
