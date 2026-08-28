"""Recovery controller helpers (phase 5, §4 / §8).

Shared by both executors so resume logic is not duplicated. A checkpoint is the
authoritative recovery source; the EventBus is never consulted for recovery.
"""

from __future__ import annotations

from typing import Any, Optional

from magent.core.result import AttemptRecord, ExecutionStatus

from .errors import CheckpointCompatibilityError
from .models import (
    CheckpointPhase,
    CheckpointRecord,
    RunRecord,
    canonical_json,
    state_schema_hash,
    state_type_name,
)

from magent.core.executor import StepRecord


def verify_compatibility(
    run: RunRecord,
    *,
    state_cls,
    workflow_id: str,
    workflow_version: str,
    initial_state,
) -> None:
    """Raise ``CheckpointCompatibilityError`` on any mismatch (no silent override)."""
    if run.state_type != state_type_name(state_cls):
        raise CheckpointCompatibilityError(
            "state type mismatch",
            field="state_type",
            expected=state_type_name(state_cls),
            actual=run.state_type,
        )
    want_hash = state_schema_hash(state_cls)
    if run.state_schema_hash != want_hash:
        raise CheckpointCompatibilityError(
            "state schema hash mismatch",
            field="state_schema_hash",
            expected=want_hash,
            actual=run.state_schema_hash,
        )
    if run.workflow_id != workflow_id:
        raise CheckpointCompatibilityError(
            "workflow id mismatch",
            field="workflow_id",
            expected=workflow_id,
            actual=run.workflow_id,
        )
    if run.workflow_version != workflow_version:
        raise CheckpointCompatibilityError(
            "workflow version mismatch",
            field="workflow_version",
            expected=workflow_version,
            actual=run.workflow_version,
        )
    if canonical_json(run.initial_state) != canonical_json(initial_state.model_dump()):
        raise CheckpointCompatibilityError(
            "initial state mismatch",
            field="initial_state",
            expected=canonical_json(initial_state.model_dump())[:64],
            actual=canonical_json(run.initial_state)[:64],
        )


async def load_history(
    store,
    run_id: str,
    *,
    state_cls,
    workflow_id: str,
    workflow_version: str,
    initial_state,
) -> tuple[RunRecord, list[CheckpointRecord]]:
    run = await store.load_run(run_id)
    verify_compatibility(
        run,
        state_cls=state_cls,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        initial_state=initial_state,
    )
    checkpoints = await store.list_checkpoints(run_id)
    return run, checkpoints


def _reconstruct_step(cp: CheckpointRecord) -> StepRecord:
    attempts = [AttemptRecord(**a) for a in cp.attempts]
    return StepRecord(
        order=0,  # callers renumber
        node_id=cp.node_id,
        agent_name=cp.node_id or "",
        status=ExecutionStatus.SUCCESS,
        started_at=cp.created_at,
        finished_at=cp.created_at,
        duration_ms=0.0,
        attempts=attempts,
        terminal_reason="success",
        message=(cp.output_state or {}).get("__message__"),
        error=cp.attempts[-1].get("error") if cp.attempts else None,
    )


def build_sequential_resume(
    checkpoints: list[CheckpointRecord], agents
) -> dict[str, Any]:
    committed_steps: list[StepRecord] = []
    restored_state: Optional[dict] = None
    next_index = 0
    abandoned = 0
    from_seq = 0
    started_nodes: set[str] = set()
    committed_nodes: set[str] = set()

    for cp in checkpoints:
        from_seq = max(from_seq, cp.checkpoint_seq)
        if cp.phase == CheckpointPhase.NODE_STARTED and cp.node_id is not None:
            started_nodes.add(cp.node_id)
        elif cp.phase == CheckpointPhase.NODE_COMMITTED and cp.node_id is not None:
            step = _reconstruct_step(cp)
            step.order = len(committed_steps)
            committed_steps.append(step)
            restored_state = cp.output_state
            committed_nodes.add(cp.node_id)
            next_index = len(committed_steps)

    # A NODE_STARTED with no following NODE_COMMITTED means a crashed attempt.
    for cp in checkpoints:
        if cp.phase == CheckpointPhase.NODE_STARTED and cp.node_id not in committed_nodes:
            abandoned += 1

    return {
        "committed_steps": committed_steps,
        "restored_state": restored_state,
        "next_index": next_index,
        "abandoned": abandoned,
        "from_seq": from_seq,
    }


def build_graph_resume(
    checkpoints: list[CheckpointRecord], graph, state_cls
) -> dict[str, Any]:
    out_state: dict[str, Any] = {}
    updates: dict[str, dict] = {}
    status: dict[str, Any] = {}
    activated: dict[str, set[str]] = {}
    committed_steps: dict[str, StepRecord] = {}
    abandoned = 0
    from_seq = 0
    started_nodes: set[str] = set()
    committed_nodes: set[str] = set()

    for cp in checkpoints:
        from_seq = max(from_seq, cp.checkpoint_seq)
        if cp.phase == CheckpointPhase.NODE_STARTED and cp.node_id is not None:
            started_nodes.add(cp.node_id)
        elif cp.phase == CheckpointPhase.NODE_COMMITTED and cp.node_id is not None:
            out_state[cp.node_id] = state_cls.model_validate(cp.output_state)
            updates[cp.node_id] = cp.updates or {}
            status[cp.node_id] = ExecutionStatus.SUCCESS
            if cp.activated_nodes:
                activated[cp.node_id] = set(cp.activated_nodes)
            step = _reconstruct_step(cp)
            step.node_id = cp.node_id
            step.agent_name = graph.nodes[cp.node_id].name
            committed_steps[cp.node_id] = step
            committed_nodes.add(cp.node_id)

    # A NODE_STARTED with no following NODE_COMMITTED means a crashed attempt.
    for cp in checkpoints:
        if cp.phase == CheckpointPhase.NODE_STARTED and cp.node_id not in committed_nodes:
            abandoned += 1

    return {
        "out_state": out_state,
        "updates": updates,
        "status": status,
        "activated": activated,
        "committed_steps": committed_steps,
        "abandoned": abandoned,
        "from_seq": from_seq,
    }
