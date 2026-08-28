"""Sequential executor for phase 1, extended with phase-4/phase-5 reliability.

The executor answers three questions for the minimal kernel:

1. How is an agent uniformly described and invoked? (``BaseAgent``)
2. How does an agent read state and return updates? (``AgentResult``)
3. How does the framework run several agents in a fixed order, retry transient
   failures, enforce node timeouts, persist commit boundaries, and recover from
   an interruption?

Phase 4 adds an optional :class:`ReliabilityPolicy` (retry + timeout). With the
default policy (``max_attempts=1``, no timeout, ``fail_fast``) behaviour is
identical to the original phase-1 executor.

Phase 5 adds an optional :class:`CheckpointStore`. With no store the executor is
byte-for-byte the original behaviour (no file is created, no overhead). With a
store it writes a ``NODE_STARTED`` snapshot before each node and atomically
commits the merged state + frontier after a successful node, enabling
:func:`SequentialExecutor.resume`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from pydantic import BaseModel

from magent.core.agent import BaseAgent
from magent.core.errors import AgentError, DuplicateAgentNameError, StateUpdateError
from magent.core.result import AgentResult, AttemptRecord, ExecutionStatus
from magent.core.runtime import Runtime, new_run_id
from magent.core.state import merge_updates
from magent.events import Event


class StepRecord(BaseModel):
    """Record of a single agent's execution within a run."""

    order: int
    agent_name: str
    node_id: Optional[str] = None
    status: ExecutionStatus
    started_at: float
    finished_at: float
    duration_ms: float
    message: Optional[str] = None
    error: Optional[dict[str, Any]] = None
    wait_ms: float = 0.0
    attempts: list[AttemptRecord] = []
    terminal_reason: Optional[str] = None


class ExecutionReport(BaseModel):
    """Structured report of one executor run."""

    run_id: str
    initial_state: dict[str, Any]
    final_state: dict[str, Any]
    steps: list[StepRecord] = []
    started_at: float
    finished_at: float
    duration_ms: float
    success: bool = True
    peak_concurrency: int = 0
    event_stats: Optional[dict[str, Any]] = None
    cancellation_reason: Optional[str] = None
    retry_count: int = 0
    timeout_count: int = 0
    resumed: bool = False
    resumed_from_seq: Optional[int] = None
    abandoned_attempts: int = 0
    replayed_nodes: list[str] = []

    @property
    def failed_agent(self) -> Optional[str]:
        """Name of the agent that failed, if any."""
        for step in self.steps:
            if step.status == ExecutionStatus.FAILED:
                return step.agent_name
        return None


class SequentialExecutor:
    """Runs a fixed list of agents in order, merging their updates.

    Args:
        agents: Agents to execute, in order. Names must be unique.
        conflict_strategy: ``"overwrite"`` (default) lets a later agent
            replace a field an earlier agent set; ``"reject"`` fails the
            agent if it tries to update a field already modified this run.
        run_id: Optional fixed run id (mainly for tests / reproducibility).
        clock: Optional ``() -> float`` used for timings, injectable for tests.
        reliability: Optional :class:`ReliabilityPolicy`. Defaults to no retry
            and no timeout, preserving the original phase-1 behaviour.
        checkpoint_store: Optional :class:`CheckpointStore`. When set, commit
            boundaries are persisted and :func:`resume` can continue an
            interrupted run. When ``None`` no checkpoint is written.
        workflow_id / workflow_version: Stable identifiers for compatibility
            checks on resume. ``node_version`` is read per-agent.
    """

    def __init__(
        self,
        agents: list[BaseAgent],
        *,
        conflict_strategy: str = "overwrite",
        run_id: Optional[str] = None,
        clock: Optional[Callable[[], float]] = None,
        reliability=None,
        sleeper=None,
        rng=None,
        event_bus=None,
        checkpoint_store=None,
        workflow_id: str = "sequential",
        workflow_version: str = "1",
    ) -> None:
        if conflict_strategy not in ("overwrite", "reject"):
            raise ValueError(f"unknown conflict_strategy: {conflict_strategy!r}")
        self.agents = list(agents)
        self.conflict_strategy = conflict_strategy
        self._run_id = run_id
        self._clock = clock or time.time
        self._reliability = reliability
        self._sleeper = sleeper
        self._rng = rng
        self._bus = event_bus
        self._checkpoint_store = checkpoint_store
        self._workflow_id = workflow_id
        self._workflow_version = workflow_version
        self._validate_names()

    def _validate_names(self) -> None:
        names = [agent.name for agent in self.agents]
        seen: set[str] = set()
        for name in names:
            if name in seen:
                raise DuplicateAgentNameError(name)
            seen.add(name)

    def _node_version(self, agent: BaseAgent) -> str:
        return getattr(agent, "version", "1")

    async def run(self, initial_state: BaseModel) -> tuple[BaseModel, ExecutionReport]:
        return await self._execute(initial_state, resumed=False, resume_run_id=None)

    async def resume(
        self, run_id: str, initial_state: BaseModel
    ) -> tuple[BaseModel, ExecutionReport]:
        if self._checkpoint_store is None:
            raise ValueError("resume requires a checkpoint_store")
        return await self._execute(initial_state, resumed=True, resume_run_id=run_id)

    async def _execute(
        self, initial_state: BaseModel, *, resumed: bool, resume_run_id: Optional[str]
    ) -> tuple[BaseModel, ExecutionReport]:
        from magent.checkpoint.models import (
            CheckpointPhase,
            CheckpointRecord,
            RunRecord,
            state_schema_hash,
            state_type_name,
        )
        from magent.checkpoint.recovery import build_sequential_resume, load_history
        from magent.reliability.runner import run_node
        from magent.reliability.policy import ReliabilityPolicy

        policy = self._reliability or ReliabilityPolicy()
        store = self._checkpoint_store
        state_cls = type(initial_state)
        state_type = state_type_name(state_cls)
        state_hash = state_schema_hash(state_cls)
        run_id = resume_run_id or self._run_id or new_run_id()
        started = self._clock()
        rc: dict[str, Any] = {}
        state = initial_state

        bus = self._bus

        async def emit(topic: str, data: dict) -> None:
            if bus is not None:
                await bus.publish(Event(topic=topic, payload=data, run_id=run_id))

        seq = [0]

        async def _cp(phase, **kw) -> None:
            if store is None:
                return
            rec = CheckpointRecord(
                run_id=run_id,
                workflow_id=self._workflow_id,
                workflow_version=self._workflow_version,
                state_type=state_type,
                state_schema_hash=state_hash,
                checkpoint_seq=seq[0],
                phase=phase,
                created_at=self._clock(),
                **kw,
            )
            await store.append(rec)
            seq[0] += 1

        if resumed:
            _run, checkpoints = await load_history(
                store,
                run_id,
                state_cls=state_cls,
                workflow_id=self._workflow_id,
                workflow_version=self._workflow_version,
                initial_state=initial_state,
            )
            rc = build_sequential_resume(checkpoints, self.agents)
            state = (
                state_cls.model_validate(rc["restored_state"])
                if rc["restored_state"] is not None
                else initial_state
            )
            steps: list[StepRecord] = list(rc["committed_steps"])
            seq[0] = rc["from_seq"] + 1
            next_index = rc["next_index"]
            abandoned = rc["abandoned"]
            replayed: list[str] = []
        else:
            steps = []
            next_index = 0
            abandoned = 0
            replayed = []
            if store is not None:
                await store.create_run(
                    RunRecord(
                        run_id=run_id,
                        workflow_id=self._workflow_id,
                        workflow_version=self._workflow_version,
                        state_type=state_type,
                        state_schema_hash=state_hash,
                        initial_state=initial_state.model_dump(),
                        status=CheckpointPhase.RUN_STARTED.value,
                        created_at=started,
                        updated_at=started,
                    )
                )
                await _cp(CheckpointPhase.RUN_STARTED, input_state=initial_state.model_dump(),
                )

        updated_fields: set[str] = set()
        success = True
        caller_cancelled = False

        try:
            for index in range(next_index, len(self.agents)):
                agent = self.agents[index]
                if not success:
                    now = self._clock()
                    steps.append(
                        StepRecord(
                            order=index,
                            node_id=agent.name, agent_name=agent.name,
                            status=ExecutionStatus.NOT_EXECUTED,
                            started_at=now,
                            finished_at=now,
                            duration_ms=0.0,
                        )
                    )
                    continue

                if resumed:
                    replayed.append(agent.name)

                runtime = Runtime(
                    run_id=run_id,
                    agent_name=agent.name,
                    started_at=self._clock(),
                    logger=logging.getLogger(f"magent.{agent.name}"),
                    clock=self._clock,
                )
                step_start = self._clock()
                log: list[AttemptRecord] = []
                await _cp(CheckpointPhase.NODE_STARTED,
                    node_id=agent.name,
                    node_version=self._node_version(agent),
                    attempt=1,
                    input_state=state.model_dump(),
                )
                try:
                    outcome = await run_node(
                        agent,
                        state,
                        runtime,
                        policy=policy,
                        sleeper=self._sleeper,
                        rng=self._rng,
                        clock=self._clock,
                        emit=emit,
                        attempts_log=log,
                    )
                except asyncio.CancelledError:
                    now = self._clock()
                    steps.append(
                        StepRecord(
                            order=index,
                            node_id=agent.name, agent_name=agent.name,
                            status=ExecutionStatus.CANCELLED,
                            started_at=step_start,
                            finished_at=now,
                            duration_ms=(now - step_start) * 1000,
                            attempts=log,
                            terminal_reason="cancelled",
                        )
                    )
                    caller_cancelled = True
                    break

                if outcome.status == ExecutionStatus.SKIPPED:
                    now = self._clock()
                    steps.append(
                        StepRecord(
                            order=index,
                            node_id=agent.name, agent_name=agent.name,
                            status=ExecutionStatus.SKIPPED,
                            started_at=step_start,
                            finished_at=now,
                            duration_ms=(now - step_start) * 1000,
                            attempts=outcome.attempts,
                            terminal_reason=outcome.terminal_reason,
                            message=(
                                outcome.result.message
                                if outcome.result is not None
                                else None
                            ),
                        )
                    )
                    await _cp(CheckpointPhase.NODE_COMMITTED,
                        node_id=agent.name,
                        node_version=self._node_version(agent),
                        output_state=state.model_dump(),
                        updates={},
                        frontier={"next_index": index + 1},
                        attempts=[a.model_dump() for a in outcome.attempts],
                    )
                    continue

                if outcome.status == ExecutionStatus.SUCCESS:
                    result = outcome.result
                    assert result is not None
                    conflict = False
                    for key in result.updates:
                        if key in updated_fields and self.conflict_strategy == "reject":
                            success = False
                            now = self._clock()
                            steps.append(
                                StepRecord(
                                    order=index,
                                    node_id=agent.name, agent_name=agent.name,
                                    status=ExecutionStatus.FAILED,
                                    started_at=step_start,
                                    finished_at=now,
                                    duration_ms=(now - step_start) * 1000,
                                    attempts=outcome.attempts,
                                    terminal_reason="failed",
                                    error={
                                        "type": "StateUpdateError",
                                        "reason": f"conflicting update on field '{key}'",
                                    },
                                )
                            )
                            conflict = True
                            break
                        updated_fields.add(key)
                    if conflict:
                        continue
                    try:
                        state = merge_updates(state, result.updates)
                    except StateUpdateError as exc:
                        success = False
                        now = self._clock()
                        steps.append(
                            StepRecord(
                                order=index,
                                node_id=agent.name, agent_name=agent.name,
                                status=ExecutionStatus.FAILED,
                                started_at=step_start,
                                finished_at=now,
                                duration_ms=(now - step_start) * 1000,
                                attempts=outcome.attempts,
                                terminal_reason="failed",
                                error={"type": "StateUpdateError", "reason": exc.reason},
                            )
                        )
                        continue
                    now = self._clock()
                    steps.append(
                        StepRecord(
                            order=index,
                            node_id=agent.name, agent_name=agent.name,
                            status=ExecutionStatus.SUCCESS,
                            started_at=step_start,
                            finished_at=now,
                            duration_ms=(now - step_start) * 1000,
                            attempts=outcome.attempts,
                            terminal_reason=outcome.terminal_reason,
                            message=result.message,
                            error=result.error,
                        )
                    )
                    await _cp(CheckpointPhase.NODE_COMMITTED,
                        node_id=agent.name,
                        node_version=self._node_version(agent),
                        output_state=state.model_dump(),
                        updates=dict(result.updates),
                        frontier={"next_index": index + 1},
                        attempts=[a.model_dump() for a in outcome.attempts],
                    )
                    continue

                # Terminal FAILED (incl. timeout). Fail-fast: stop the run.
                success = False
                now = self._clock()
                steps.append(
                    StepRecord(
                        order=index,
                        node_id=agent.name, agent_name=agent.name,
                        status=ExecutionStatus.FAILED,
                        started_at=step_start,
                        finished_at=now,
                        duration_ms=(now - step_start) * 1000,
                        attempts=outcome.attempts,
                        terminal_reason=outcome.terminal_reason,
                        message=outcome.result.message if outcome.result else None,
                        error=outcome.error,
                    )
                )
        except asyncio.CancelledError:
            caller_cancelled = True

        if caller_cancelled:
            recorded_names = {s.agent_name for s in steps}
            now = self._clock()
            for index, agent in enumerate(self.agents):
                if agent.name not in recorded_names:
                    steps.append(
                        StepRecord(
                            order=index,
                            node_id=agent.name, agent_name=agent.name,
                            status=ExecutionStatus.NOT_EXECUTED,
                            started_at=now,
                            finished_at=now,
                            duration_ms=0.0,
                            terminal_reason="cancelled",
                        )
                    )
            success = False

        finished = self._clock()
        retry_count = sum(max(0, len(s.attempts) - 1) for s in steps)
        timeout_count = sum(
            1
            for s in steps
            for a in s.attempts
            if a.error and a.error.get("type") == "NodeTimeoutError"
        )
        if store is not None:
            if caller_cancelled:
                phase = CheckpointPhase.RUN_CANCELLED
            elif success:
                phase = CheckpointPhase.RUN_COMPLETED
            else:
                phase = CheckpointPhase.RUN_FAILED
            await _cp(phase,
                output_state=state.model_dump(),
            )
            await store.update_run_status(run_id, phase.value)
        report = ExecutionReport(
            run_id=run_id,
            initial_state=initial_state.model_dump(),
            final_state=state.model_dump(),
            steps=steps,
            started_at=started,
            finished_at=finished,
            duration_ms=(finished - started) * 1000,
            success=success,
            cancellation_reason="caller" if caller_cancelled else None,
            retry_count=retry_count,
            timeout_count=timeout_count,
            resumed=resumed,
            resumed_from_seq=rc["from_seq"] if resumed else None,
            abandoned_attempts=abandoned,
            replayed_nodes=replayed,
        )
        return state, report
