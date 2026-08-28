"""Single-process, sequential graph executor (phase 2).

Walks one path from the entry point to ``END``. At each node it runs the
agent, merges the returned updates (reusing phase-1 ``merge_updates`` and
fail-fast semantics), then selects the next node: an unconditional edge, or a
conditional edge whose ``router(state)`` label is resolved through the
mapping. Only the selected branch executes; unselected conditional targets are
recorded as ``NOT_EXECUTED`` so the report distinguishes visited / failed /
unvisited branches.
"""

from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel

from magent.core.agent import BaseAgent
from magent.core.errors import AgentError
from magent.core.executor import ExecutionReport, StepRecord
from magent.core.result import AgentResult, ExecutionStatus
from magent.core.runtime import Runtime, new_run_id
from magent.core.state import merge_updates

from .model import CompiledGraph, END


class GraphExecutor:
    def __init__(self, graph: CompiledGraph, *, run_id: str | None = None, clock=None) -> None:
        self._graph = graph
        self._run_id = run_id
        self._clock = clock or time.time

    async def run(self, initial_state: BaseModel) -> tuple[BaseModel, ExecutionReport]:
        graph = self._graph
        run_id = self._run_id or new_run_id()
        started = self._clock()
        state = initial_state
        steps: list[StepRecord] = []
        order = 0
        success = True
        current = graph.entry

        while current != END and success:
            agent: BaseAgent = graph.nodes[current]
            node_id = current
            runtime = Runtime(
                run_id=run_id,
                agent_name=agent.name,
                started_at=self._clock(),
                logger=logging.getLogger(f"magent.{node_id}"),
                clock=self._clock,
            )
            step_start = self._clock()
            try:
                result = await agent.run(state, runtime)
                step_end = self._clock()
                if not isinstance(result, AgentResult):
                    raise AgentError(agent.name, run_id, "agent did not return an AgentResult")

                if result.status == ExecutionStatus.FAILED:
                    success = False
                    steps.append(
                        StepRecord(
                            order=order,
                            node_id=node_id,
                            agent_name=agent.name,
                            status=ExecutionStatus.FAILED,
                            started_at=step_start,
                            finished_at=step_end,
                            duration_ms=(step_end - step_start) * 1000,
                            message=result.message,
                            error=result.error,
                        )
                    )
                    break

                if result.status == ExecutionStatus.SKIPPED:
                    steps.append(
                        StepRecord(
                            order=order,
                            node_id=node_id,
                            agent_name=agent.name,
                            status=ExecutionStatus.SKIPPED,
                            started_at=step_start,
                            finished_at=step_end,
                            duration_ms=(step_end - step_start) * 1000,
                            message=result.message,
                        )
                    )
                    order += 1
                else:
                    state = merge_updates(state, result.updates)
                    steps.append(
                        StepRecord(
                            order=order,
                            node_id=node_id,
                            agent_name=agent.name,
                            status=ExecutionStatus.SUCCESS,
                            started_at=step_start,
                            finished_at=step_end,
                            duration_ms=(step_end - step_start) * 1000,
                            message=result.message,
                            error=result.error,
                        )
                    )
                    order += 1

                if current in graph.conditional:
                    router, mapping = graph.conditional[current]
                    try:
                        if asyncio.iscoroutinefunction(router):
                            label = await router(state)
                        else:
                            label = router(state)
                    except Exception as exc:  # noqa: BLE001 - normalize routing failure
                        fail_end = self._clock()
                        steps.append(
                            StepRecord(
                                order=order,
                                node_id=node_id,
                                agent_name=agent.name,
                                status=ExecutionStatus.FAILED,
                                started_at=step_start,
                                finished_at=fail_end,
                                duration_ms=(fail_end - step_start) * 1000,
                                error={
                                    "type": "GraphRoutingError",
                                    "message": str(exc),
                                    "cause": type(exc).__name__,
                                },
                            )
                        )
                        success = False
                        break
                    if label not in mapping:
                        fail_end = self._clock()
                        steps.append(
                            StepRecord(
                                order=order,
                                node_id=node_id,
                                agent_name=agent.name,
                                status=ExecutionStatus.FAILED,
                                started_at=step_start,
                                finished_at=fail_end,
                                duration_ms=(fail_end - step_start) * 1000,
                                error={
                                    "type": "GraphRoutingError",
                                    "reason": f"unknown routing label '{label}'",
                                },
                            )
                        )
                        success = False
                        break
                    for lab, target in mapping.items():
                        if lab != label and target != END:
                            now = self._clock()
                            steps.append(
                                StepRecord(
                                    order=order,
                                    node_id=target,
                                    agent_name=graph.nodes[target].name,
                                    status=ExecutionStatus.NOT_EXECUTED,
                                    started_at=now,
                                    finished_at=now,
                                    duration_ms=0.0,
                                )
                            )
                            order += 1
                    current = mapping[label]
                elif current in graph.edges:
                    current = graph.edges[current]
                else:
                    fail_end = self._clock()
                    steps.append(
                        StepRecord(
                            order=order,
                            node_id=node_id,
                            agent_name=agent.name,
                            status=ExecutionStatus.FAILED,
                            started_at=step_start,
                            finished_at=fail_end,
                            duration_ms=(fail_end - step_start) * 1000,
                            error={
                                "type": "GraphValidationError",
                                "reason": "node has no outgoing edge",
                            },
                        )
                    )
                    success = False
                    break
            except Exception as exc:  # noqa: BLE001 - normalize to AgentError
                step_end = self._clock()
                success = False
                err = AgentError(agent.name, run_id, str(exc), cause=exc)
                steps.append(
                    StepRecord(
                        order=order,
                        node_id=node_id,
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
                break

        # Any node never reached (downstream of a failure, or an uncovered
        # branch) is recorded as NOT_EXECUTED so the report distinguishes
        # visited / failed / unvisited nodes.
        visited_node_ids = {s.node_id for s in steps if s.node_id is not None}
        for nid, agent in graph.nodes.items():
            if nid not in visited_node_ids:
                now = self._clock()
                steps.append(
                    StepRecord(
                        order=order,
                        node_id=nid,
                        agent_name=agent.name,
                        status=ExecutionStatus.NOT_EXECUTED,
                        started_at=now,
                        finished_at=now,
                        duration_ms=0.0,
                    )
                )
                order += 1

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
