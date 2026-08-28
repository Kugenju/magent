"""Sequential executor for phase 1, extended with phase-4 reliability.

The executor answers three questions for the minimal kernel:

1. How is an agent uniformly described and invoked? (``BaseAgent``)
2. How does an agent read state and return updates? (``AgentResult``)
3. How does the framework run several agents in a fixed order, retry transient
   failures, enforce node timeouts, and record what happened?

Phase 4 adds an optional :class:`ReliabilityPolicy` (retry + timeout). With the
default policy (``max_attempts=1``, no timeout, ``fail_fast``) behaviour is
identical to the original phase-1 executor.
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
        self._validate_names()

    def _validate_names(self) -> None:
        names = [agent.name for agent in self.agents]
        seen: set[str] = set()
        for name in names:
            if name in seen:
                raise DuplicateAgentNameError(name)
            seen.add(name)

    async def run(self, initial_state: BaseModel) -> tuple[BaseModel, ExecutionReport]:
        from magent.reliability.runner import run_node
        from magent.reliability.policy import ReliabilityPolicy

        policy = self._reliability or ReliabilityPolicy()
        run_id = self._run_id or new_run_id()

        bus = self._bus

        async def emit(topic: str, data: dict) -> None:
            if bus is not None:
                await bus.publish(Event(topic=topic, payload=data, run_id=run_id))
        started = self._clock()
        state = initial_state
        updated_fields: set[str] = set()
        steps: list[StepRecord] = []
        success = True
        caller_cancelled = False

        try:
            for index, agent in enumerate(self.agents):
                if not success:
                    now = self._clock()
                    steps.append(
                        StepRecord(
                            order=index,
                            agent_name=agent.name,
                            status=ExecutionStatus.NOT_EXECUTED,
                            started_at=now,
                            finished_at=now,
                            duration_ms=0.0,
                        )
                    )
                    continue

                runtime = Runtime(
                    run_id=run_id,
                    agent_name=agent.name,
                    started_at=self._clock(),
                    logger=logging.getLogger(f"magent.{agent.name}"),
                    clock=self._clock,
                )
                step_start = self._clock()
                log: list[AttemptRecord] = []
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
                            agent_name=agent.name,
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
                            agent_name=agent.name,
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
                                    agent_name=agent.name,
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
                                agent_name=agent.name,
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
                            agent_name=agent.name,
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
                    continue

                # Terminal FAILED (incl. timeout). Fail-fast: stop the run.
                success = False
                now = self._clock()
                steps.append(
                    StepRecord(
                        order=index,
                        agent_name=agent.name,
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
                            agent_name=agent.name,
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
        )
        return state, report
