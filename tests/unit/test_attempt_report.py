import asyncio
import logging

import pytest
from pydantic import BaseModel

from magent import (
    AgentResult,
    BaseAgent,
    END,
    EventBus,
    ExecutionStatus,
    GraphBuilder,
    ReliabilityPolicy,
    RetryableError,
    RetryPolicy,
    SequentialExecutor,
    TimeoutPolicy,
)
from magent.core.runtime import Runtime, new_run_id
from magent.reliability.runner import run_node


class S(BaseModel):
    value: int = 0


def noop_sleeper(_=0):
    return asyncio.sleep(0)


class RetryThenOk(BaseAgent):
    def __init__(self, name, fail_times):
        super().__init__(name)
        self.calls = 0
        self.fail_times = fail_times

    async def run(self, state, runtime):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RetryableError("transient")
        return AgentResult(updates={"value": state.value + 1})


class SlowAgent(BaseAgent):
    def __init__(self, name="slow"):
        super().__init__(name)

    async def run(self, state, runtime):
        await asyncio.sleep(30)
        return AgentResult(updates={"value": 1})


def test_attempt_record_fields():
    agent = RetryThenOk("a", fail_times=1)

    async def main():
        return await run_node(
            agent,
            S(),
            Runtime(
                run_id=new_run_id(),
                agent_name="a",
                started_at=0.0,
                logger=logging.getLogger("test"),
            ),
            policy=ReliabilityPolicy(
                retry=RetryPolicy(max_attempts=3, backoff_base=0.0)
            ),
            sleeper=noop_sleeper,
            rng=lambda: 0.0,
        )

    outcome = asyncio.run(main())
    assert len(outcome.attempts) == 2
    a0 = outcome.attempts[0]
    assert a0.attempt == 1
    assert a0.status == ExecutionStatus.FAILED
    assert a0.started_at is not None
    assert a0.finished_at is not None
    assert a0.duration_ms >= 0
    assert outcome.attempts[1].status == ExecutionStatus.SUCCESS
    assert outcome.attempts[1].attempt == 2


def test_step_record_exposes_attempts_and_terminal_reason():
    agent = RetryThenOk("a", fail_times=1)

    async def main():
        return await SequentialExecutor(
            [agent],
            reliability=ReliabilityPolicy(
                retry=RetryPolicy(max_attempts=3, backoff_base=0.0)
            ),
            sleeper=noop_sleeper,
            rng=lambda: 0.0,
        ).run(S())

    state, report = asyncio.run(main())
    step = report.steps[0]
    assert step.terminal_reason == "success"
    assert len(step.attempts) == 2
    assert step.attempts[0].status == ExecutionStatus.FAILED
    assert step.attempts[1].status == ExecutionStatus.SUCCESS


def test_timeout_attempt_record():
    agent = SlowAgent()

    async def main():
        return await run_node(
            agent,
            S(),
            Runtime(
                run_id=new_run_id(),
                agent_name="slow",
                started_at=0.0,
                logger=logging.getLogger("test"),
            ),
            policy=ReliabilityPolicy(
                retry=RetryPolicy(max_attempts=1),
                timeout=TimeoutPolicy(node_timeout=0.01),
            ),
            sleeper=noop_sleeper,
            rng=lambda: 0.0,
        )

    outcome = asyncio.run(main())
    a0 = outcome.attempts[0]
    assert a0.status == ExecutionStatus.FAILED
    assert a0.error.get("type") == "NodeTimeoutError"


def test_attempt_events_published_on_event_bus():
    agent = RetryThenOk("a", fail_times=1)
    bus = EventBus()
    captured = []

    async def handler(evt):
        captured.append(evt.topic)

    async def main():
        await bus.subscribe("agent.attempt.*", handler)
        return await SequentialExecutor(
            [agent],
            reliability=ReliabilityPolicy(
                retry=RetryPolicy(max_attempts=3, backoff_base=0.0)
            ),
            sleeper=noop_sleeper,
            rng=lambda: 0.0,
            event_bus=bus,
        ).run(S())

    asyncio.run(main())
    assert "agent.attempt.started" in captured
    assert "agent.attempt.failed" in captured
    assert "agent.attempt.succeeded" in captured


def test_graph_attempt_record_with_parallel():
    class A(BaseAgent):
        async def run(self, s, r):
            return AgentResult(updates={"value": 1})

    b = RetryThenOk("b", fail_times=1)

    g = (
        GraphBuilder()
        .add_node("a", A("a"))
        .add_node("b", b)
        .set_entry_point("a")
        .add_edge("a", "b")
        .add_edge("b", END)
        .compile()
    )

    async def main():
        return await g.run(
            S(),
            reliability=ReliabilityPolicy(
                retry=RetryPolicy(max_attempts=3, backoff_base=0.0)
            ),
            sleeper=noop_sleeper,
            rng=lambda: 0.0,
        )

    state, report = asyncio.run(main())
    b_step = next(s for s in report.steps if s.agent_name == "b")
    assert len(b_step.attempts) == 2
    assert b_step.terminal_reason == "success"
