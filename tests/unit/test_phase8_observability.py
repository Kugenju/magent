"""阶段 8 — 观测数据模型与记录器测试（≥30 个新测试的一部分）。"""

from __future__ import annotations

from magent.core.executor import ExecutionReport, StepRecord
from magent.core.result import AttemptRecord, ExecutionStatus
from magent.events import Event
from magent.events.bus import InMemoryEventBus
from magent.observability import (
    RunSummary,
    Span,
    SpanStatus,
    Trace,
    TraceCollector,
    build_observability,
    redact,
    to_jsonl,
    write_json,
    write_jsonl,
)

_TRACE = dict(trace_id="t", run_id="r", workflow_id="w", workflow_version="1", state_schema_version="h", status="success")


def _report(steps, *, success=True, resumed=False, replayed=None, retry_count=0, timeout_count=0, peak=1):
    return ExecutionReport(
        run_id="r1",
        initial_state={},
        final_state={},
        started_at=1.0,
        finished_at=2.0,
        duration_ms=1000.0,
        success=success,
        peak_concurrency=peak,
        retry_count=retry_count,
        timeout_count=timeout_count,
        resumed=resumed,
        resumed_from_seq=5 if resumed else None,
        replayed_nodes=replayed or [],
        steps=steps,
    )


def _step(node, status, attempts):
    return StepRecord(
        order=0,
        node_id=node,
        agent_name=node,
        status=status,
        started_at=1.0,
        finished_at=1.5,
        duration_ms=500.0,
        attempts=attempts,
    )


def _attempt(n, status, error=None):
    return AttemptRecord(attempt=n, started_at=1.0, finished_at=1.5, duration_ms=500.0, status=status, error=error)


# ---- 脱敏 ----
def test_redact_hides_secret_keys():
    out = redact({"api_key": "sk-123", "nested": {"token": "x"}, "ok": 1})
    assert out["api_key"] == "<redacted>"
    assert out["nested"]["token"] == "<redacted>"
    assert out["ok"] == 1


def test_redact_truncates_long_strings():
    out = redact("a" * 5000, max_str=10)
    assert out == "a" * 10 + "...<truncated>"
    assert len(out) == 24


def test_redact_limits_depth():
    out = redact({"a": {"b": {"c": {"d": 1}}}}, max_depth=2)
    assert out["a"]["b"] == "<nested>"


def test_redact_limits_keys():
    out = redact({f"k{i}": i for i in range(100)}, max_keys=10)
    assert len(out) == 10


def test_redact_limits_list_items():
    out = redact(list(range(100)), max_items=10)
    assert len(out) == 10


# ---- 模型 ----
def test_span_status_values():
    assert SpanStatus.TIMEOUT.value == "timeout"
    assert SpanStatus.NOT_EXECUTED.value == "not_executed"


def test_models_serialize():
    t = Trace(**_TRACE)
    s = Span(span_id="s", trace_id="t", node_id="n", agent_name="a", status=SpanStatus.SUCCESS)
    assert t.model_dump_json()
    assert s.model_dump_json()


def test_to_jsonl_one_line_per_record():
    t = Trace(**_TRACE)
    s = Span(span_id="s", trace_id="t", node_id="n", agent_name="a", status=SpanStatus.SUCCESS)
    text = to_jsonl([t, s])
    assert text.count("\n") == 2


def test_write_jsonl_and_json(tmp_path):
    t = Trace(**_TRACE)
    s = Span(span_id="s", trace_id="t", node_id="n", agent_name="a", status=SpanStatus.SUCCESS)
    write_jsonl(str(tmp_path / "t.jsonl"), [t, s])
    write_json(str(tmp_path / "s.json"), t)
    assert (tmp_path / "t.jsonl").exists()
    assert (tmp_path / "s.json").exists()


# ---- build_observability ----
def test_build_success():
    rep = _report([_step("a", ExecutionStatus.SUCCESS, [_attempt(1, ExecutionStatus.SUCCESS)])])
    t, spans, summary = build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h")
    assert t.status == "success"
    assert len(spans) == 1
    assert summary.node_count == 1
    assert summary.success_count == 1


def test_build_retry_spans():
    rep = _report(
        [_step("b", ExecutionStatus.FAILED, [_attempt(1, ExecutionStatus.FAILED, {"type": "AgentError"}), _attempt(2, ExecutionStatus.FAILED, {"type": "AgentError"})])],
        success=False,
        retry_count=1,
    )
    t, spans, summary = build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h")
    assert summary.retry_count == 1
    assert summary.failure_count == 1
    retry_span = [s for s in spans if s.attempt == 2][0]
    assert retry_span.retry_reason == "retry"
    assert retry_span.status == SpanStatus.FAILED


def test_build_timeout_status():
    rep = _report(
        [_step("b", ExecutionStatus.FAILED, [_attempt(1, ExecutionStatus.FAILED, {"type": "NodeTimeoutError"})])],
        success=False,
        timeout_count=1,
    )
    t, spans, summary = build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h")
    assert spans[0].status == SpanStatus.TIMEOUT
    assert summary.timeout_count == 1


def test_build_cancelled():
    rep = _report([_step("b", ExecutionStatus.CANCELLED, [])], success=False)
    t, spans, summary = build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h")
    assert spans[0].status == SpanStatus.CANCELLED
    assert summary.cancelled_count == 1


def test_build_not_executed():
    rep = _report([_step("b", ExecutionStatus.NOT_EXECUTED, [])], success=False)
    t, spans, summary = build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h")
    assert spans[0].status == SpanStatus.NOT_EXECUTED
    assert summary.not_executed_count == 1


def test_build_recovery():
    rep = _report([_step("a", ExecutionStatus.SUCCESS, [_attempt(1, ExecutionStatus.SUCCESS)])], resumed=True, replayed=["x"])
    t, spans, summary = build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h")
    assert summary.recovery_count == 1
    assert summary.replayed_nodes == ["x"]


def test_build_checkpoint_writes():
    cps = [object() for _ in range(3)]
    rep = _report([_step("a", ExecutionStatus.SUCCESS, [_attempt(1, ExecutionStatus.SUCCESS)])])
    t, spans, summary = build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h", checkpoint_records=cps)
    assert summary.checkpoint_writes == 3


def test_utc_conversion():
    rep = _report([_step("a", ExecutionStatus.SUCCESS, [_attempt(1, ExecutionStatus.SUCCESS)])])
    t, _, _ = build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h")
    assert t.started_at is not None
    assert t.started_at.tzinfo is not None


def test_summary_counts_sum_to_node_count():
    rep = _report(
        [
            _step("a", ExecutionStatus.SUCCESS, [_attempt(1, ExecutionStatus.SUCCESS)]),
            _step("b", ExecutionStatus.FAILED, [_attempt(1, ExecutionStatus.FAILED)]),
            _step("c", ExecutionStatus.CANCELLED, []),
            _step("d", ExecutionStatus.NOT_EXECUTED, []),
        ],
        success=False,
    )
    t, spans, summary = build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h")
    assert summary.node_count == 4
    assert summary.success_count + summary.failure_count + summary.cancelled_count + summary.not_executed_count + summary.skipped_count == 4


def test_build_does_not_mutate_report():
    rep = _report([_step("a", ExecutionStatus.SUCCESS, [_attempt(1, ExecutionStatus.SUCCESS)])])
    before = rep.model_dump()
    build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h")
    assert rep.model_dump() == before


def test_build_no_secret_leak():
    rep = _report([_step("a", ExecutionStatus.SUCCESS, [_attempt(1, ExecutionStatus.SUCCESS)])])
    t, spans, summary = build_observability(rep, workflow_id="graph", workflow_version="1", state_schema_version="h")
    blob = (t.model_dump_json() + to_jsonl(spans) + summary.model_dump_json()).lower()
    assert "api_key" not in blob
    assert "secret" not in blob


# ---- collector + EventBus ----
async def test_collector_enriches_event_count():
    bus = InMemoryEventBus()
    collector = TraceCollector("graph", "1", "h")
    await collector.attach(bus)
    await bus.publish(Event(topic="agent.completed", run_id="r1", source="a"))
    await bus.publish(Event(topic="agent.retry", run_id="r1", source="b"))
    rep = _report([_step("a", ExecutionStatus.SUCCESS, [_attempt(1, ExecutionStatus.SUCCESS)])])
    t, spans, summary = collector.build(rep)
    assert t.metadata["event_count"] >= 2
    assert t.metadata["event_topics"].get("agent.completed") >= 1
    collector.detach()


async def test_collector_isolation_does_not_fail():
    bus = InMemoryEventBus()
    collector = TraceCollector("graph", "1", "h")
    await collector.attach(bus)
    rep = _report([_step("a", ExecutionStatus.SUCCESS, [_attempt(1, ExecutionStatus.SUCCESS)])])
    t, spans, summary = collector.build(rep)
    assert summary.success_count == 1
    collector.detach()
