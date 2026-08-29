"""阶段 8 观测记录器（Task 2）。

记录器只消费 ``ExecutionReport``、``Checkpoint`` 历史与（可选）``EventBus`` 事件；
不修改 State，不作为恢复依据。关闭记录器时，业务结果与未启用观测完全一致。

权威来源：节点 attempt、错误、重试、超时、取消来自 ``StepRecord`` / attempt 生命周期；
最终成功与节点汇总来自 ``ExecutionReport``；Checkpoint 写入、恢复序号、重放节点来自
``Checkpoint`` 历史 / resume 报告。EventBus 仅用于补全事件计数，不作为真相来源。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

from magent.core.executor import ExecutionReport
from magent.core.result import ExecutionStatus

from .models import (
    RunSummary,
    Span,
    SpanStatus,
    Trace,
    _dt,
    _new_id,
    redact_metadata,
)

_STATUS_MAP = {
    ExecutionStatus.SUCCESS: SpanStatus.SUCCESS,
    ExecutionStatus.SKIPPED: SpanStatus.SKIPPED,
    ExecutionStatus.FAILED: SpanStatus.FAILED,
    ExecutionStatus.CANCELLED: SpanStatus.CANCELLED,
    ExecutionStatus.NOT_EXECUTED: SpanStatus.NOT_EXECUTED,
}


def _attempt_status(attempt, terminal_reason: Optional[str]) -> SpanStatus:
    if attempt.error and attempt.error.get("type") == "NodeTimeoutError":
        return SpanStatus.TIMEOUT
    if terminal_reason == "timeout" and attempt.status == ExecutionStatus.FAILED:
        return SpanStatus.TIMEOUT
    return _STATUS_MAP[attempt.status]


def _trace_status(report: ExecutionReport) -> str:
    if report.cancellation_reason:
        return "cancelled"
    if report.success:
        if any(s.status == ExecutionStatus.FAILED for s in report.steps):
            return "partial"
        return "success"
    return "failed"


def build_observability(
    report: ExecutionReport,
    *,
    workflow_id: str,
    workflow_version: str,
    state_schema_version: str,
    trace_id: Optional[str] = None,
    checkpoint_records: Optional[Iterable[Any]] = None,
    redact_fields: Optional[Iterable[str]] = None,
) -> Tuple[Trace, list[Span], RunSummary]:
    """从权威来源（report + 可选 checkpoint）生成 Trace / Span / RunSummary。"""
    tid = trace_id or _new_id()

    resumed = bool(report.resumed)
    meta = redact_metadata(
        {
            "event_stats": report.event_stats,
            "cancellation_reason": report.cancellation_reason,
            "abandoned_attempts": report.abandoned_attempts,
            "resumed": resumed,
            "resumed_from_seq": report.resumed_from_seq,
            "replayed_nodes": report.replayed_nodes,
        },
        redact_fields=redact_fields or set(),
    )
    trace = Trace(
        trace_id=tid,
        run_id=report.run_id,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        state_schema_version=state_schema_version,
        started_at=_dt(report.started_at),
        finished_at=_dt(report.finished_at),
        status=_trace_status(report),
        metadata=meta,
    )

    spans: list[Span] = []
    for step in report.steps:
        base = {
            "trace_id": tid,
            "node_id": step.node_id or step.agent_name,
            "agent_name": step.agent_name,
        }
        if step.attempts:
            for a in step.attempts:
                status = _attempt_status(a, step.terminal_reason)
                spans.append(
                    Span(
                        span_id=f"{base['node_id']}#{a.attempt}",
                        parent_span_id=None,
                        attempt=a.attempt,
                        queued_ms=step.wait_ms if a.attempt == 1 else 0.0,
                        duration_ms=a.duration_ms,
                        status=status,
                        error_type=(a.error or {}).get("type") if a.error else None,
                        retry_reason="retry" if (a.attempt > 1 and status != SpanStatus.SKIPPED) else None,
                        metadata=redact_metadata(
                            {"terminal_reason": step.terminal_reason, "message": step.message},
                            redact_fields=redact_fields or set(),
                        ),
                        **base,
                    )
                )
        else:
            status = _STATUS_MAP[step.status]
            spans.append(
                Span(
                    span_id=f"{base['node_id']}#1",
                    parent_span_id=None,
                    attempt=1,
                    queued_ms=step.wait_ms,
                    duration_ms=step.duration_ms,
                    status=status,
                    error_type=(step.error or {}).get("type") if step.error else None,
                    cancellation_reason=step.terminal_reason if status == SpanStatus.CANCELLED else None,
                    metadata=redact_metadata(
                        {"terminal_reason": step.terminal_reason, "message": step.message},
                        redact_fields=redact_fields or set(),
                    ),
                    **base,
                )
            )

    success_count = sum(1 for s in report.steps if s.status == ExecutionStatus.SUCCESS)
    failure_count = sum(1 for s in report.steps if s.status == ExecutionStatus.FAILED)
    cancelled_count = sum(1 for s in report.steps if s.status == ExecutionStatus.CANCELLED)
    skipped_count = sum(1 for s in report.steps if s.status == ExecutionStatus.SKIPPED)
    not_executed_count = sum(1 for s in report.steps if s.status == ExecutionStatus.NOT_EXECUTED)

    cp_writes = len(list(checkpoint_records)) if checkpoint_records is not None else 0
    summary = RunSummary(
        trace_id=tid,
        run_id=report.run_id,
        node_count=len(report.steps),
        success_count=success_count,
        failure_count=failure_count,
        cancelled_count=cancelled_count,
        skipped_count=skipped_count,
        not_executed_count=not_executed_count,
        retry_count=report.retry_count,
        timeout_count=report.timeout_count,
        peak_concurrency=report.peak_concurrency,
        checkpoint_writes=cp_writes,
        recovery_count=1 if resumed else 0,
        replayed_nodes=list(report.replayed_nodes),
        duration_ms=report.duration_ms,
        resource_samples=None,
    )
    return trace, spans, summary


class TraceCollector:
    """可选 EventBus 订阅者 + 记录构建器。对执行完全只读。"""

    def __init__(
        self,
        workflow_id: str,
        workflow_version: str,
        state_schema_version: str,
        *,
        redact_fields: Optional[Iterable[str]] = None,
        bus=None,
    ) -> None:
        self._workflow_id = workflow_id
        self._workflow_version = workflow_version
        self._state_schema_version = state_schema_version
        self._redact_fields = set(redact_fields or ())
        self._events: list[dict] = []
        self._trace_id = _new_id()
        self._sub = None
        self._bus = None

    async def attach(self, bus) -> None:
        self._bus = bus
        self._sub = await bus.subscribe("agent.*", self._on_event)

    def _on_event(self, event) -> None:
        self._events.append(
            {
                "topic": event.topic,
                "source": event.source,
                "payload": redact_metadata(event.payload or {}, redact_fields=self._redact_fields),
            }
        )

    def detach(self) -> None:
        if self._bus is not None and self._sub is not None:
            self._bus.unsubscribe("agent.*", self._on_event)

    def build(
        self, report: ExecutionReport, *, checkpoint_records=None
    ) -> Tuple[Trace, list[Span], RunSummary]:
        trace, spans, summary = build_observability(
            report,
            workflow_id=self._workflow_id,
            workflow_version=self._workflow_version,
            state_schema_version=self._state_schema_version,
            trace_id=self._trace_id,
            checkpoint_records=checkpoint_records,
            redact_fields=self._redact_fields,
        )
        topics: dict[str, int] = {}
        for e in self._events:
            topics[e["topic"]] = topics.get(e["topic"], 0) + 1
        trace.metadata = redact_metadata(
            {**trace.metadata, "event_count": len(self._events), "event_topics": topics},
            redact_fields=self._redact_fields,
        )
        return trace, spans, summary
