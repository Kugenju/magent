"""Sequential executor for phase 1.

The executor answers three questions for the minimal kernel:

1. How is an agent uniformly described and invoked? (``BaseAgent``)
2. How does an agent read state and return updates? (``AgentResult``)
3. How does the framework run several agents in a fixed order and record
   what happened? (``SequentialExecutor`` + ``ExecutionReport``)

Policy in phase 1:

- Agents run in registration order, one at a time.
- Default error policy is **fail-fast**: if an agent raises or returns
  ``FAILED``, the run stops; later agents are marked ``NOT_EXECUTED``.
- No retry, no checkpoint, no concurrency (those are later phases).
- A conflicting field update under the ``reject`` strategy fails the agent.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from pydantic import BaseModel

from .agent import BaseAgent
from .errors import AgentError, DuplicateAgentNameError, StateUpdateError
from .result import AgentResult, ExecutionStatus
from .runtime import Runtime, new_run_id
from .state import merge_updates


class StepRecord(BaseModel):
    """Record of a single agent's execution within a run."""

    order: int
    agent_name: str
    status: ExecutionStatus
    started_at: float
    finished_at: float
    duration_ms: float
    message: Optional[str] = None
    error: Optional[dict[str, Any]] = None


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
    """

    def __init__(
        self,
        agents: list[BaseAgent],
        *,
        conflict_strategy: str = "overwrite",
        run_id: Optional[str] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if conflict_strategy not in ("overwrite", "reject"):
            raise ValueError(f"unknown conflict_strategy: {conflict_strategy!r}")
        self.agents = list(agents)
        self.conflict_strategy = conflict_strategy
        self._run_id = run_id
        self._clock = clock or time.time
        self._validate_names()

    def _validate_names(self) -> None:
        names = [agent.name for agent in self.agents]
        seen: set[str] = set()
        for name in names:
            if name in seen:
                raise DuplicateAgentNameError(name)
            seen.add(name)

    async def run(self, initial_state: BaseModel) -> tuple[BaseModel, ExecutionReport]:
        """Execute all agents and return the final state and a report.

        On the first failure the run stops (fail-fast). Already-completed
        steps keep their status; not-yet-started agents are recorded as
        ``NOT_EXECUTED``.
        """
        run_id = self._run_id or new_run_id()
        started = self._clock()
        state = initial_state
        updated_fields: set[str] = set()
        steps: list[StepRecord] = []
        success = True

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
            )
            step_start = self._clock()
            try:
                result = await agent.run(state, runtime)
                step_end = self._clock()
                if not isinstance(result, AgentResult):
                    raise AgentError(
                        agent.name, run_id, "agent did not return an AgentResult"
                    )

                if result.status == ExecutionStatus.FAILED:
                    success = False
                    steps.append(
                        StepRecord(
                            order=index,
                            agent_name=agent.name,
                            status=ExecutionStatus.FAILED,
                            started_at=step_start,
                            finished_at=step_end,
                            duration_ms=(step_end - step_start) * 1000,
                            message=result.message,
                            error=result.error,
                        )
                    )
                    continue

                if result.status == ExecutionStatus.SKIPPED:
                    steps.append(
                        StepRecord(
                            order=index,
                            agent_name=agent.name,
                            status=ExecutionStatus.SKIPPED,
                            started_at=step_start,
                            finished_at=step_end,
                            duration_ms=(step_end - step_start) * 1000,
                            message=result.message,
                        )
                    )
                    continue

                for key in result.updates:
                    if key in updated_fields and self.conflict_strategy == "reject":
                        success = False
                        steps.append(
                            StepRecord(
                                order=index,
                                agent_name=agent.name,
                                status=ExecutionStatus.FAILED,
                                started_at=step_start,
                                finished_at=step_end,
                                duration_ms=(step_end - step_start) * 1000,
                                error={
                                    "type": "StateUpdateError",
                                    "reason": f"conflicting update on field '{key}'",
                                },
                            )
                        )
                        break
                    updated_fields.add(key)
                else:
                    state = merge_updates(state, result.updates)
                    steps.append(
                        StepRecord(
                            order=index,
                            agent_name=agent.name,
                            status=ExecutionStatus.SUCCESS,
                            started_at=step_start,
                            finished_at=step_end,
                            duration_ms=(step_end - step_start) * 1000,
                            message=result.message,
                            error=result.error,
                        )
                    )
            except StateUpdateError as exc:
                step_end = self._clock()
                success = False
                steps.append(
                    StepRecord(
                        order=index,
                        agent_name=agent.name,
                        status=ExecutionStatus.FAILED,
                        started_at=step_start,
                        finished_at=step_end,
                        duration_ms=(step_end - step_start) * 1000,
                        error={"type": "StateUpdateError", "reason": exc.reason},
                    )
                )
            except Exception as exc:  # noqa: BLE001 - normalize to AgentError
                step_end = self._clock()
                success = False
                err = AgentError(agent.name, run_id, str(exc), cause=exc)
                steps.append(
                    StepRecord(
                        order=index,
                        agent_name=agent.name,
                        status=ExecutionStatus.FAILED,
                        started_at=step_start,
                        finished_at=step_end,
                        duration_ms=(step_end - step_start) * 1000,
                        error={
                            "type": "AgentError",
                            "agent_name": agent.name,
                            "run_id": run_id,
                            "message": str(err),
                            "cause": type(exc).__name__,
                        },
                    )
                )

        finished = self._clock()
        report = ExecutionReport(
            run_id=run_id,
            initial_state=initial_state.model_dump(),
            final_state=state.model_dump(),
            steps=steps,
            started_at=started,
            finished_at=finished,
            duration_ms=(finished - started) * 1000,
            success=success,
        )
        return state, report
