from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
from pydantic import BaseModel

from magent import (
    AgentResult,
    BaseAgent,
    END,
    ExecutionStatus,
    GraphBuilder,
    InMemoryCheckpointStore,
    SqliteCheckpointStore,
    CheckpointCompatibilityError,
    CheckpointConflictError,
    CheckpointError,
    CheckpointPhase,
    CheckpointRecord,
    EffectRecord,
    SideEffectSink,
    SequentialExecutor,
    execution_key,
)
from magent.graph.executor import GraphExecutor


# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------
class State(BaseModel):
    value: int = 0
    visited: list[str] = []
    log: str = ""


class Increment(BaseAgent):
    def __init__(self, name, by=1):
        super().__init__(name)
        self.by = by

    async def run(self, state, runtime):
        return AgentResult(
            updates={
                "value": state.value + self.by,
                "visited": state.visited + [runtime.agent_name],
            }
        )


class NoOp(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"visited": state.visited + [runtime.agent_name]})


def _linear_graph():
    return (
        GraphBuilder()
        .add_node("a", Increment("a"))
        .add_node("b", Increment("b"))
        .add_node("c", Increment("c"))
        .set_entry_point("a")
        .add_edge("a", "b")
        .add_edge("b", "c")
        .add_edge("c", END)
        .compile()
    )


# --------------------------------------------------------------------------
# Store: in-memory
# --------------------------------------------------------------------------
async def test_inmemory_create_and_load_run():
    store = InMemoryCheckpointStore()
    from magent.checkpoint.models import RunRecord

    await store.create_run(
        RunRecord(
            run_id="r1",
            workflow_id="w",
            workflow_version="1",
            state_type="State",
            state_schema_hash="h",
            initial_state={"value": 0},
            status="run_started",
            created_at=1.0,
            updated_at=1.0,
        )
    )
    run = await store.load_run("r1")
    assert run.run_id == "r1"
    with pytest.raises(Exception):
        await store.load_run("missing")


def _cp(seq, node_id, phase=CheckpointPhase.NODE_COMMITTED, **kw):
    return CheckpointRecord(
        run_id="r",
        workflow_id="w",
        workflow_version="1",
        state_type="State",
        state_schema_hash="h",
        checkpoint_seq=seq,
        phase=phase,
        node_id=node_id,
        created_at=1.0,
        **kw,
    )


async def test_inmemory_append_idempotent_and_conflict():
    store = InMemoryCheckpointStore()
    cp = _cp(1, "a", output_state={"value": 1})
    await store.append(cp)
    await store.append(cp)  # idempotent, no error
    cp2 = _cp(1, "a", output_state={"value": 2})  # same seq, different content
    with pytest.raises(CheckpointConflictError):
        await store.append(cp2)


async def test_inmemory_latest_and_list():
    store = InMemoryCheckpointStore()
    for seq in range(3):
        await store.append(
            CheckpointRecord(
                run_id="r",
                workflow_id="w",
                workflow_version="1",
                state_type="State",
                state_schema_hash="h",
                checkpoint_seq=seq,
                phase=CheckpointPhase.NODE_STARTED,
                node_id=f"n{seq}",
                created_at=float(seq),
            )
        )
    latest = await store.latest("r")
    assert latest.node_id == "n2"
    allc = await store.list_checkpoints("r")
    assert [c.checkpoint_seq for c in allc] == [0, 1, 2]


async def test_inmemory_record_effect_idempotent():
    store = InMemoryCheckpointStore()
    rec = EffectRecord(
        execution_key="k1",
        run_id="r",
        node_id="a",
        node_version="1",
        status="success",
        result_json={"x": 1},
        created_at=1.0,
    )
    assert await store.record_effect(rec) is True
    assert await store.record_effect(rec) is False  # already recorded
    got = await store.get_effect("k1")
    assert got.result_json == {"x": 1}
    assert await store.get_effect("missing") is None


# --------------------------------------------------------------------------
# Store: sqlite persistence
# --------------------------------------------------------------------------
async def test_sqlite_persists_across_reopen():
    path = os.path.join(tempfile.mkdtemp(), "cp.db")
    store = SqliteCheckpointStore(path)
    await store.create_run(
        _run_record("r", {"value": 0})
    )
    await store.append(
        _cp(1, "a", output_state={"value": 5}, updates={"value": 5})
    )
    await store.close()

    store2 = SqliteCheckpointStore(path)
    run = await store2.load_run("r")
    assert run.initial_state == {"value": 0}
    cps = await store2.list_checkpoints("r")
    assert len(cps) == 1
    assert cps[0].output_state == {"value": 5}
    assert cps[0].state_type == "State"
    await store2.close()


async def test_sqlite_conflict_and_unknown_run():
    store = SqliteCheckpointStore()
    await store.create_run(_run_record("r", {"value": 0}))
    cp = _cp(1, "a", phase=CheckpointPhase.NODE_STARTED)
    await store.append(cp)
    with pytest.raises(CheckpointConflictError):
        await store.append(_cp(1, "b", phase=CheckpointPhase.NODE_STARTED))
    with pytest.raises(Exception):
        await store.append(_cp(1, "a", run_id="unknown", phase=CheckpointPhase.NODE_STARTED))


# --------------------------------------------------------------------------
# CheckpointRecord semantics
# --------------------------------------------------------------------------
def test_checkpoint_checksum_is_deterministic():
    a = CheckpointRecord(
        run_id="r", workflow_id="w", workflow_version="1",
        state_type="State", state_schema_hash="h",
        checkpoint_seq=1, phase=CheckpointPhase.NODE_COMMITTED,
        node_id="a", created_at=1.0, output_state={"value": 1},
    )
    b = CheckpointRecord(
        run_id="r", workflow_id="w", workflow_version="1",
        state_type="State", state_schema_hash="h",
        checkpoint_seq=1, phase=CheckpointPhase.NODE_COMMITTED,
        node_id="a", created_at=1.0, output_state={"value": 1},
    )
    assert a.checksum == b.checksum
    assert a.compute_checksum() == a.checksum


# --------------------------------------------------------------------------
# Sequential executor checkpoint + resume
# --------------------------------------------------------------------------
async def test_sequential_full_run_writes_checkpoints():
    store = InMemoryCheckpointStore()
    ex = SequentialExecutor([Increment("a"), Increment("b")], checkpoint_store=store)
    state, report = await ex.run(State())
    assert state.value == 2
    cps = await store.list_checkpoints(report.run_id)
    phases = [c.phase for c in cps]
    assert phases[0] == CheckpointPhase.RUN_STARTED
    assert phases[-1] == CheckpointPhase.RUN_COMPLETED
    assert any(c.phase == CheckpointPhase.NODE_COMMITTED for c in cps)
    assert report.resumed is False


async def test_sequential_resume_idempotent_when_fully_committed():
    store = InMemoryCheckpointStore()
    ex = SequentialExecutor([Increment("a"), Increment("b")], checkpoint_store=store)
    state, report = await ex.run(State())
    run_id = report.run_id

    ex2 = SequentialExecutor([Increment("a"), Increment("b")], checkpoint_store=store)
    state2, report2 = await ex2.resume(run_id, State())
    assert state2.value == 2
    assert report2.resumed is True
    assert report2.replayed_nodes == []  # nothing to replay
    assert report2.resumed_from_seq is not None


async def test_sequential_resume_after_partial_crash():
    store = InMemoryCheckpointStore()
    ex = SequentialExecutor([Increment("a"), Increment("b"), Increment("c")], checkpoint_store=store)
    state, report = await ex.run(State())
    run_id = report.run_id
    # Simulate crash: keep only up to and including `a` committed (seq < 3).
    await store.list_checkpoints(run_id)  # ensure loaded
    store._checkpoints[run_id] = [c for c in store._checkpoints[run_id] if c.checkpoint_seq < 3]

    ex2 = SequentialExecutor([Increment("a"), Increment("b"), Increment("c")], checkpoint_store=store)
    state2, report2 = await ex2.resume(run_id, State())
    assert state2.value == 3
    assert report2.resumed
    assert "a" not in report2.replayed_nodes
    assert set(report2.replayed_nodes) == {"b", "c"}
    # committed a must appear in the report steps.
    committed_a = [s for s in report2.steps if s.node_id == "a"]
    assert committed_a and committed_a[0].status == ExecutionStatus.SUCCESS


async def test_sequential_resume_counts_abandoned_dangling():
    store = InMemoryCheckpointStore()
    ex = SequentialExecutor([Increment("a"), Increment("b")], checkpoint_store=store)
    state, report = await ex.run(State())
    run_id = report.run_id
    # Keep RUN_STARTED + a STARTED + a COMMITTED + b STARTED (dangling, no commit).
    store._checkpoints[run_id] = [c for c in store._checkpoints[run_id] if c.checkpoint_seq <= 3]

    ex2 = SequentialExecutor([Increment("a"), Increment("b")], checkpoint_store=store)
    state2, report2 = await ex2.resume(run_id, State())
    assert state2.value == 2
    assert report2.abandoned_attempts == 1  # the dangling b NODE_STARTED
    assert "b" in report2.replayed_nodes


async def test_sequential_resume_compatibility_state_mismatch():
    store = InMemoryCheckpointStore()
    ex = SequentialExecutor([Increment("a")], checkpoint_store=store)
    _, report = await ex.run(State())
    run_id = report.run_id

    class OtherState(BaseModel):
        different: int = 0

    ex2 = SequentialExecutor([Increment("a")], checkpoint_store=store)
    with pytest.raises(CheckpointCompatibilityError):
        await ex2.resume(run_id, OtherState())


async def test_sequential_resume_compatibility_workflow_version():
    store = InMemoryCheckpointStore()
    ex = SequentialExecutor([Increment("a")], checkpoint_store=store, workflow_version="1")
    _, report = await ex.run(State())
    run_id = report.run_id

    ex2 = SequentialExecutor([Increment("a")], checkpoint_store=store, workflow_version="2")
    with pytest.raises(CheckpointCompatibilityError):
        await ex2.resume(run_id, State())


async def test_sequential_resume_requires_store():
    ex = SequentialExecutor([Increment("a")])
    with pytest.raises(ValueError):
        await ex.resume("r", State())


async def test_sequential_without_store_has_no_overhead():
    ex = SequentialExecutor([Increment("a"), Increment("b")])
    state, report = await ex.run(State())
    assert state.value == 2
    assert report.success


# --------------------------------------------------------------------------
# Graph executor checkpoint + resume
# --------------------------------------------------------------------------
async def test_graph_full_run_writes_checkpoints():
    store = InMemoryCheckpointStore()
    ex = GraphExecutor(_linear_graph(), checkpoint_store=store)
    state, report = await ex.run(State())
    assert state.value == 3
    cps = await store.list_checkpoints(report.run_id)
    assert cps[0].phase == CheckpointPhase.RUN_STARTED
    assert cps[-1].phase == CheckpointPhase.RUN_COMPLETED


async def test_graph_resume_after_partial_crash():
    store = InMemoryCheckpointStore()
    ex = GraphExecutor(_linear_graph(), checkpoint_store=store)
    state, report = await ex.run(State())
    run_id = report.run_id
    store._checkpoints[run_id] = [c for c in store._checkpoints[run_id] if c.checkpoint_seq < 3]

    ex2 = GraphExecutor(_linear_graph(), checkpoint_store=store)
    state2, report2 = await ex2.resume(run_id, State())
    assert state2.value == 3
    assert report2.resumed
    assert set(report2.replayed_nodes) == {"b", "c"}
    assert report2.abandoned_attempts == 0


async def test_graph_resume_fan_out_fan_in():
    class FanState(BaseModel):
        value: int = 0
        visited: list[str] = []

    FanState.reducers = {  # type: ignore[attr-defined]
        "value": lambda a, b: a + b,
        "visited": lambda a, b: a + b,
    }

    def _fan():
        return (
            GraphBuilder()
            .add_node("root", Increment("root"))
            .add_node("l", Increment("l"))
            .add_node("r", Increment("r"))
            .add_node("join", NoOp("join"))
            .set_entry_point("root")
            .add_parallel_edges("root", ["l", "r"])
            .add_join("join", ["l", "r"])
            .add_edge("join", END)
            .compile()
        )

    store = InMemoryCheckpointStore()
    ex = GraphExecutor(_fan(), checkpoint_store=store)
    state, report = await ex.run(FanState())
    run_id = report.run_id
    expected = state.model_dump()
    # crash right after root committed (seq < 3: RUN_STARTED, root STARTED, root COMMITTED)
    store._checkpoints[run_id] = [c for c in store._checkpoints[run_id] if c.checkpoint_seq < 3]

    ex2 = GraphExecutor(_fan(), checkpoint_store=store)
    state2, report2 = await ex2.resume(run_id, FanState())
    assert state2.model_dump() == expected  # resume reproduces the full result
    assert report2.resumed
    assert "root" not in report2.replayed_nodes
    assert set(report2.replayed_nodes) == {"l", "r", "join"}


async def test_graph_resume_conditional_preserves_route():
    def _route(state: State) -> str:
        return "left" if state.value >= 1 else "right"

    def _cond():
        return (
            GraphBuilder()
            .add_node("start", Increment("start"))
            .add_node("left", NoOp("left"))
            .add_node("right", NoOp("right"))
            .set_entry_point("start")
            .add_conditional_edges("start", _route, {"left": "left", "right": "right"})
            .add_edge("left", END)
            .add_edge("right", END)
            .compile()
        )

    store = InMemoryCheckpointStore()
    ex = GraphExecutor(_cond(), checkpoint_store=store)
    state, report = await ex.run(State())
    run_id = report.run_id
    store._checkpoints[run_id] = [c for c in store._checkpoints[run_id] if c.checkpoint_seq < 3]

    ex2 = GraphExecutor(_cond(), checkpoint_store=store)
    state2, report2 = await ex2.resume(run_id, State())
    assert state2.visited == ["start", "left"]
    statuses = {s.node_id: s.status for s in report2.steps}
    assert statuses["left"] == ExecutionStatus.SUCCESS
    assert statuses["right"] == ExecutionStatus.NOT_EXECUTED


# --------------------------------------------------------------------------
# Idempotency helpers
# --------------------------------------------------------------------------
def test_execution_key_is_stable_and_ignores_attempt():
    k1 = execution_key("r", "a", "1", {"x": 1}, "send_email")
    k2 = execution_key("r", "a", "1", {"x": 1}, "send_email")
    assert k1 == k2
    # different input state => different key
    k3 = execution_key("r", "a", "1", {"x": 2}, "send_email")
    assert k1 != k3


async def test_side_effect_sink_records_once():
    store = InMemoryCheckpointStore()
    calls = []

    async def effect_fn(payload):
        calls.append(payload)
        return {"ok": True, "n": len(calls)}

    sink = SideEffectSink(store, run_id="r", node_id="a", node_version="1", clock=lambda: 1.0)
    out1 = await sink.write({"v": 1}, "send_email", {"v": 1}, effect_fn)
    out2 = await sink.write({"v": 1}, "send_email", {"v": 1}, effect_fn)
    assert out1 == out2
    assert len(calls) == 1  # effect only executed once
    assert sink.write_count == 1


async def test_side_effect_sink_replays_recorded():
    store = InMemoryCheckpointStore()
    rec = EffectRecord(
        execution_key=execution_key("r", "a", "1", {"v": 1}, "send_email"),
        run_id="r", node_id="a", node_version="1",
        status="success", result_json={"done": True}, created_at=1.0,
    )
    assert await store.record_effect(rec) is True

    calls = []

    async def effect_fn(payload):
        calls.append(payload)
        return {"fresh": True}

    sink = SideEffectSink(store, run_id="r", node_id="a", node_version="1", clock=lambda: 1.0)
    # Different effect_fn; recorded result must be returned, effect_fn not called.
    out = await sink.write({"v": 1}, "send_email", {"v": 1}, effect_fn)
    assert out == {"done": True}
    assert calls == []


# --------------------------------------------------------------------------
# Phase 5 release gates
# --------------------------------------------------------------------------
async def test_sqlite_checksum_verification_on_read():
    import sqlite3 as _sql

    path = os.path.join(tempfile.mkdtemp(), "cp.db")
    store = SqliteCheckpointStore(path)
    await store.create_run(_run_record("r", {"value": 0}))
    await store.append(_cp(1, "a", output_state={"value": 5}))
    await store.close()
    # Corrupt the persisted checksum.
    conn = _sql.connect(path)
    conn.execute("UPDATE checkpoints SET checksum='deadbeef' WHERE checkpoint_seq=1")
    conn.commit()
    conn.close()
    store2 = SqliteCheckpointStore(path)
    with pytest.raises(CheckpointError):
        await store2.list_checkpoints("r")
    await store2.close()


class SlowBoom(BaseAgent):
    async def run(self, state, runtime):
        raise RuntimeError("boom")


async def test_run_record_status_reflects_terminal():
    store = InMemoryCheckpointStore()
    ex = SequentialExecutor([Increment("a"), Increment("b")], checkpoint_store=store)
    _, report = await ex.run(State())
    run = await store.load_run(report.run_id)
    assert run.status == "run_completed"

    store2 = InMemoryCheckpointStore()
    ex2 = SequentialExecutor([SlowBoom("x"), Increment("y")], checkpoint_store=store2)
    _, report2 = await ex2.run(State())
    assert report2.success is False
    run2 = await store2.load_run(report2.run_id)
    assert run2.status == "run_failed"


class Versioned(Increment):
    def __init__(self, name, by=1, version="2"):
        super().__init__(name, by)
        self.version = version


async def test_node_version_and_frontier_in_checkpoint():
    store = InMemoryCheckpointStore()
    ex = SequentialExecutor([Versioned("a", version="2"), Increment("b")], checkpoint_store=store)
    _, report = await ex.run(State())
    cps = await store.list_checkpoints(report.run_id)
    committed = [c for c in cps if c.phase == CheckpointPhase.NODE_COMMITTED]
    assert committed
    assert all(c.node_version == "2" for c in committed if c.node_id == "a")
    # Every committed checkpoint carries a frontier.
    assert all(c.frontier is not None for c in committed)


async def test_graph_checkpoint_seq_unique_under_concurrency():
    class FanState(BaseModel):
        value: int = 0
        visited: list[str] = []

    FanState.reducers = {"value": lambda a, b: a + b, "visited": lambda a, b: a + b}  # type: ignore[attr-defined]

    def _fan():
        return (
            GraphBuilder()
            .add_node("root", Increment("root"))
            .add_node("l", Increment("l"))
            .add_node("r", Increment("r"))
            .add_node("join", NoOp("join"))
            .set_entry_point("root")
            .add_parallel_edges("root", ["l", "r"])
            .add_join("join", ["l", "r"])
            .add_edge("join", END)
            .compile()
        )

    store = InMemoryCheckpointStore()
    ex = GraphExecutor(_fan(), checkpoint_store=store, max_concurrency=8)
    await ex.run(FanState())
    seqs = [c.checkpoint_seq for c in await store.list_checkpoints(ex._run_id)]
    assert len(seqs) == len(set(seqs))  # no duplicate seq under concurrency


async def test_side_effect_sink_concurrent_atomic_claim():
    store = InMemoryCheckpointStore()
    calls = []

    async def effect_fn(payload):
        await asyncio.sleep(0.01)
        calls.append(1)
        return {"n": len(calls)}

    sink = SideEffectSink(store, run_id="r", node_id="a", node_version="1", clock=lambda: 1.0)
    await asyncio.gather(*[sink.write({"v": 1}, "op", {"v": 1}, effect_fn) for _ in range(10)])
    assert len(calls) == 1  # atomic claim => effect ran exactly once
    assert sink.write_count == 1


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _run_record(run_id, initial):
    from magent.checkpoint.models import RunRecord

    return RunRecord(
        run_id=run_id,
        workflow_id="w",
        workflow_version="1",
        state_type="State",
        state_schema_hash="h",
        initial_state=initial,
        status="run_started",
        created_at=1.0,
        updated_at=1.0,
    )
