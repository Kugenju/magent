"""Unified single-node runner with timeout, retry and cleanup (phase 4, §10).

This runner is shared by :class:`SequentialExecutor` and the graph executors so
that retry/timeout semantics never diverge between them. It returns a
:class:`NodeRunOutcome` describing the terminal result and the full attempt
history; it never merges state (that stays the executor's job, and only a
successful attempt's updates are merged).
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from magent.core.agent import BaseAgent
from magent.core.errors import AgentError
from magent.core.result import AgentResult, AttemptRecord, ExecutionStatus
from magent.core.runtime import Runtime

from .errors import classify_exception, classify_result


@dataclass
class NodeRunOutcome:
    status: ExecutionStatus
    result: Optional[AgentResult]
    attempts: list[AttemptRecord]
    terminal_reason: str  # success | skipped | failed | timeout | cancelled
    error: Optional[dict[str, Any]]


async def _sleep_backoff(attempt: int, retry, sleeper, rng, emit) -> None:
    delay = retry.backoff_delay(attempt, rng)
    if emit:
        await emit("agent.retry", {"next_attempt": attempt + 1, "delay": delay})
    await sleeper(delay)


async def run_node(
    agent: BaseAgent,
    state,
    runtime: Runtime,
    *,
    policy,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: Callable[[], float] = random.random,
    clock=time.time,
    emit: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    attempts_log: Optional[list[AttemptRecord]] = None,
) -> NodeRunOutcome:
    if attempts_log is None:
        attempts_log = []
    if sleeper is None:
        sleeper = asyncio.sleep
    if rng is None:
        rng = random.random
    retry = policy.retry
    node_timeout = policy.timeout.node_timeout
    attempt = 0

    while True:
        attempt += 1
        started = clock()
        if emit:
            await emit("agent.attempt.started", {"attempt": attempt})
        try:
            if node_timeout is not None:
                try:
                    result = await asyncio.wait_for(
                        agent.run(state, runtime), timeout=node_timeout
                    )
                except asyncio.TimeoutError:
                    finished = clock()
                    rec = AttemptRecord(
                        attempt=attempt,
                        started_at=started,
                        finished_at=finished,
                        duration_ms=(finished - started) * 1000,
                        status=ExecutionStatus.FAILED,
                        error={
                            "type": "NodeTimeoutError",
                            "reason": "node exceeded timeout",
                            "timeout": node_timeout,
                        },
                    )
                    attempts_log.append(rec)
                    if emit:
                        await emit("agent.attempt.timeout", {"attempt": attempt})
                    if retry.should_retry(attempt):
                        await _sleep_backoff(attempt, retry, sleeper, rng, emit)
                        continue
                    return NodeRunOutcome(
                        ExecutionStatus.FAILED,
                        None,
                        attempts_log,
                        "timeout",
                        rec.error,
                    )
            else:
                result = await agent.run(state, runtime)
        except asyncio.CancelledError:
            finished = clock()
            attempts_log.append(
                AttemptRecord(
                    attempt=attempt,
                    started_at=started,
                    finished_at=finished,
                    duration_ms=(finished - started) * 1000,
                    status=ExecutionStatus.CANCELLED,
                    error=None,
                )
            )
            raise
        except Exception as exc:  # noqa: BLE001 - normalize to AgentError
            finished = clock()
            retryable = classify_exception(exc, retry.retryable_exceptions)
            err = AgentError(agent.name, runtime.run_id, str(exc), cause=exc)
            rec = AttemptRecord(
                attempt=attempt,
                started_at=started,
                finished_at=finished,
                duration_ms=(finished - started) * 1000,
                status=ExecutionStatus.FAILED,
                error={
                    "type": "AgentError",
                    "agent_name": agent.name,
                    "run_id": runtime.run_id,
                    "message": str(err),
                    "cause": type(exc).__name__,
                },
            )
            attempts_log.append(rec)
            if emit:
                await emit("agent.attempt.failed", {"attempt": attempt, "retryable": retryable})
            if retryable and retry.should_retry(attempt):
                await _sleep_backoff(attempt, retry, sleeper, rng, emit)
                continue
            return NodeRunOutcome(
                ExecutionStatus.FAILED, None, attempts_log, "failed", rec.error
            )
        else:
            if not isinstance(result, AgentResult):
                finished = clock()
                rec = AttemptRecord(
                    attempt=attempt,
                    started_at=started,
                    finished_at=finished,
                    duration_ms=(finished - started) * 1000,
                    status=ExecutionStatus.FAILED,
                    error={
                        "type": "AgentError",
                        "agent_name": agent.name,
                        "run_id": runtime.run_id,
                        "message": "agent did not return an AgentResult",
                    },
                )
                attempts_log.append(rec)
                if emit:
                    await emit("agent.attempt.failed", {"attempt": attempt, "retryable": False})
                if retry.should_retry(attempt):
                    await _sleep_backoff(attempt, retry, sleeper, rng, emit)
                    continue
                return NodeRunOutcome(
                    ExecutionStatus.FAILED, None, attempts_log, "failed", rec.error
                )

            if result.status in (ExecutionStatus.SUCCESS, ExecutionStatus.SKIPPED):
                finished = clock()
                attempts_log.append(
                    AttemptRecord(
                        attempt=attempt,
                        started_at=started,
                        finished_at=finished,
                        duration_ms=(finished - started) * 1000,
                        status=result.status,
                        error=result.error,
                    )
                )
                if emit:
                    await emit("agent.attempt.succeeded", {"attempt": attempt})
                reason = (
                    "success" if result.status == ExecutionStatus.SUCCESS else "skipped"
                )
                return NodeRunOutcome(
                    result.status, result, attempts_log, reason, None
                )

            # Agent returned FAILED.
            finished = clock()
            retryable = classify_result(result)
            attempts_log.append(
                AttemptRecord(
                    attempt=attempt,
                    started_at=started,
                    finished_at=finished,
                    duration_ms=(finished - started) * 1000,
                    status=ExecutionStatus.FAILED,
                    error=result.error,
                )
            )
            if emit:
                await emit("agent.attempt.failed", {"attempt": attempt, "retryable": retryable})
            if retryable and retry.should_retry(attempt):
                await _sleep_backoff(attempt, retry, sleeper, rng, emit)
                continue
            return NodeRunOutcome(
                ExecutionStatus.FAILED, result, attempts_log, "failed", result.error
            )
