import asyncio
import logging

import pytest
from pydantic import BaseModel

from magent import (
    AgentResult,
    BaseAgent,
    END,
    ExecutionStatus,
    GraphBuilder,
    ReliabilityPolicy,
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


class SlowAgent(BaseAgent):
    def __init__(self, name="slow", hang_for=5.0):
        super().__init__(name)
        self.hang_for = hang_for

    async def run(self, state, runtime):
        await asyncio.sleep(self.hang_for)
        return AgentResult(updates={"value": 1})


class TimeoutThenSucceed(BaseAgent):
    def __init__(self, name="flaky"):
        super().__init__(name)
        self.calls = 0

    async def run(self, state, runtime):
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(5)
        return AgentResult(updates={"value": state.value + 1})


async def test_node_timeout_records_timeout_attempt():
    agent = SlowAgent()
    policy = ReliabilityPolicy(
        retry=RetryPolicy(max_attempts=1),
        timeout=TimeoutPolicy(node_timeout=0.01),
    )
    rt = Runtime(
        run_id=new_run_id(),
        agent_name=agent.name,
        started_at=0.0,
        logger=logging.getLogger("test"),
    )
    outcome = await run_node(
        agent, S(), rt, policy=policy, sleeper=noop_sleeper, rng=lambda: 0.0
    )
    assert outcome.status == ExecutionStatus.FAILED
    assert outcome.terminal_reason == "timeout"
    assert outcome.attempts[0].status == ExecutionStatus.FAILED
    assert outcome.attempts[0].error.get("type") == "NodeTimeoutError"


async def test_timeout_is_retried_then_succeeds():
    agent = TimeoutThenSucceed()
    policy = ReliabilityPolicy(
        retry=RetryPolicy(max_attempts=3, backoff_base=0.0),
        timeout=TimeoutPolicy(node_timeout=0.01),
    )
    rt = Runtime(
        run_id=new_run_id(),
        agent_name=agent.name,
        started_at=0.0,
        logger=logging.getLogger("test"),
    )
    outcome = await run_node(
        agent, S(), rt, policy=policy, sleeper=noop_sleeper, rng=lambda: 0.0
    )
    assert outcome.status == ExecutionStatus.SUCCESS
    assert outcome.terminal_reason == "success"
    assert len(outcome.attempts) == 2
    assert outcome.attempts[0].status == ExecutionStatus.FAILED
    assert outcome.attempts[0].error.get("type") == "NodeTimeoutError"


async def test_sequential_report_counts_timeouts():
    agent = SlowAgent()
    policy = ReliabilityPolicy(
        retry=RetryPolicy(max_attempts=3, backoff_base=0.0),
        timeout=TimeoutPolicy(node_timeout=0.01),
    )
    state, report = await SequentialExecutor(
        [agent], reliability=policy, sleeper=noop_sleeper, rng=lambda: 0.0
    ).run(S())
    assert report.success is False
    assert report.timeout_count == 3
    assert report.retry_count == 2
    assert report.steps[0].terminal_reason == "timeout"


async def test_graph_node_timeout_fails_fast():
    b = SlowAgent("b")
    policy = ReliabilityPolicy(
        retry=RetryPolicy(max_attempts=1),
        timeout=TimeoutPolicy(node_timeout=0.01),
    )

    class A(BaseAgent):
        async def run(self, state, runtime):
            return AgentResult(updates={"value": 1})

    class C(BaseAgent):
        async def run(self, state, runtime):
            return AgentResult(updates={"value": state.value + 1})

    g = (
        GraphBuilder()
        .add_node("a", A("a"))
        .add_node("b", b)
        .add_node("c", C("c"))
        .set_entry_point("a")
        .add_edge("a", "b")
        .add_edge("b", "c")
        .add_edge("c", END)
        .compile()
    )
    state, report = await g.run(
        S(), reliability=policy, sleeper=noop_sleeper, rng=lambda: 0.0
    )
    assert report.success is False
    assert report.timeout_count == 1
    assert report.steps[1].terminal_reason == "timeout"
    assert report.steps[2].status == ExecutionStatus.NOT_EXECUTED
