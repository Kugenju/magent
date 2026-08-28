import asyncio

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
)
from magent.core.runtime import Runtime, new_run_id
from magent.reliability.runner import run_node


class S(BaseModel):
    value: int = 0


def noop_sleeper(_=0):
    return asyncio.sleep(0)


class HangingAgent(BaseAgent):
    def __init__(self, name="hang"):
        super().__init__(name)

    async def run(self, state, runtime):
        await asyncio.sleep(30)
        return AgentResult(updates={"value": 1})


async def test_sequential_caller_cancellation_returns_report():
    agent = HangingAgent()
    task = asyncio.create_task(SequentialExecutor([agent]).run(S()))
    await asyncio.sleep(0.02)
    task.cancel()
    state, report = await task
    assert report.cancellation_reason == "caller"
    assert report.success is False
    assert report.steps[0].status == ExecutionStatus.CANCELLED
    assert report.steps[0].terminal_reason == "cancelled"


async def test_graph_caller_cancellation_cancels_remaining():
    class A(BaseAgent):
        async def run(self, s, r):
            return AgentResult(updates={"value": 1})

    b, c = HangingAgent("b"), HangingAgent("c")

    class D(BaseAgent):
        async def run(self, s, r):
            return AgentResult(updates={"value": s.value})

    g = (
        GraphBuilder()
        .add_node("a", A("a"))
        .add_node("b", b)
        .add_node("c", c)
        .add_node("d", D("d"))
        .add_parallel_edges("a", ["b", "c"])
        .add_join("d", ["b", "c"])
        .set_entry_point("a")
        .add_edge("d", END)
        .compile()
    )
    task = asyncio.create_task(g.run(S()))
    await asyncio.sleep(0.05)
    task.cancel()
    state, report = await task
    assert report.cancellation_reason == "caller"
    assert report.success is False
    statuses = {s.agent_name: s.status for s in report.steps}
    assert statuses["b"] == ExecutionStatus.CANCELLED
    assert statuses["c"] == ExecutionStatus.CANCELLED
    assert statuses["d"] == ExecutionStatus.NOT_EXECUTED


async def test_partial_steps_before_cancellation_succeed():
    class Fast(BaseAgent):
        async def run(self, s, r):
            return AgentResult(updates={"value": s.value + 1})

    fast, hang = Fast("fast"), HangingAgent("hang")
    task = asyncio.create_task(SequentialExecutor([fast, hang]).run(S()))
    await asyncio.sleep(0.05)
    task.cancel()
    state, report = await task
    assert report.cancellation_reason == "caller"
    by_name = {s.agent_name: s for s in report.steps}
    assert by_name["fast"].status == ExecutionStatus.SUCCESS
    assert by_name["hang"].status == ExecutionStatus.CANCELLED
