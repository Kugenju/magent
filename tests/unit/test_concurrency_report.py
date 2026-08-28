"""Tests for concurrency lifecycle, cancellation and the structured report (phase 3, §6/§10)."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from magent import (
    AgentResult,
    BaseAgent,
    END,
    EventBus,
    ExecutionStatus,
    GraphBuilder,
    GraphExecutor,
)

END = "__end__"


class _Noop(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult()


class Boomer(BaseAgent):
    async def run(self, state, runtime):
        raise RuntimeError("boom")


class SlowWriter(BaseAgent):
    def __init__(self, name: str, updates: dict, delay: float = 0.05) -> None:
        super().__init__(name)
        self.updates = updates
        self.delay = delay

    async def run(self, state, runtime):
        await asyncio.sleep(self.delay)
        return AgentResult(updates=self.updates)


class ReportState(BaseModel):
    c: str = ""


def _failure_diamond(write_field: bool) -> GraphBuilder:
    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    b.add_node("b", Boomer("b"))
    if write_field:
        b.add_node("c", SlowWriter("c", {"c": "C"}))
    else:
        b.add_node("c", SlowWriter("c", {}))
    b.add_node("d", _Noop("d"))
    (
        b.set_entry_point("a")
        .add_parallel_edges("a", ["b", "c"])
        .add_edge("b", "d")
        .add_edge("c", "d")
        .add_join("d", ["b", "c"])
        .add_edge("d", END)
    )
    return b


async def test_failure_cancels_siblings_and_not_executed_downstream():
    state, report = await _failure_diamond(False).compile().run(ReportState())
    assert report.success is False
    statuses = {s.node_id: s.status for s in report.steps}
    assert statuses["b"] == ExecutionStatus.FAILED
    assert statuses["c"] in (ExecutionStatus.CANCELLED, ExecutionStatus.NOT_EXECUTED)
    assert statuses["d"] == ExecutionStatus.NOT_EXECUTED


async def test_cancelled_branch_result_is_not_merged():
    state, report = await _failure_diamond(True).compile().run(ReportState())
    assert report.success is False
    # C was cancelled, so its update must not reach the final state.
    assert state.c == ""


def _diamond_nodes(b: GraphBuilder) -> GraphBuilder:
    b.add_node("a", _Noop("a"))
    b.add_node("b", _Noop("b"))
    b.add_node("c", _Noop("c"))
    b.add_node("d", _Noop("d"))
    (
        b.set_entry_point("a")
        .add_parallel_edges("a", ["b", "c"])
        .add_edge("b", "d")
        .add_edge("c", "d")
        .add_join("d", ["b", "c"])
        .add_edge("d", END)
    )
    return b


async def test_one_final_record_per_node():
    b = _diamond_nodes(GraphBuilder())
    _, report = await b.compile().run(ReportState())
    node_ids = [s.node_id for s in report.steps]
    assert len(node_ids) == len(set(node_ids))
    assert sorted(node_ids) == ["a", "b", "c", "d"]


async def test_peak_concurrency_recorded():
    class Ctr:
        def __init__(self):
            self.cur = 0
            self.peak = 0

    counter = Ctr()

    class CA(BaseAgent):
        def __init__(self, name, ctr, delay=0.02):
            super().__init__(name)
            self.ctr = ctr
            self.delay = delay

        async def run(self, state, runtime):
            self.ctr.cur += 1
            self.ctr.peak = max(self.ctr.peak, self.ctr.cur)
            try:
                await asyncio.sleep(self.delay)
                return AgentResult()
            finally:
                self.ctr.cur -= 1

    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    b.add_node("b", CA("b", counter))
    b.add_node("c", CA("c", counter))
    b.add_node("d", _Noop("d"))
    (
        b.set_entry_point("a")
        .add_parallel_edges("a", ["b", "c"])
        .add_edge("b", "d")
        .add_edge("c", "d")
        .add_join("d", ["b", "c"])
        .add_edge("d", END)
    )
    _, report = await b.compile().run(ReportState())
    assert report.peak_concurrency == 2


async def test_wait_time_is_recorded_and_non_negative():
    b = _diamond_nodes(GraphBuilder())
    _, report = await b.compile().run(ReportState())
    for step in report.steps:
        assert step.wait_ms >= 0.0
        assert isinstance(step.wait_ms, float)


async def test_event_stats_present_when_bus_supplied():
    bus = EventBus()
    received = []
    await bus.subscribe("agent.completed", lambda e: received.append(e))

    b = _diamond_nodes(GraphBuilder())
    _, report = await b.compile().run(ReportState(), event_bus=bus)
    assert report.event_stats is not None
    assert report.event_stats["published"] > 0
    assert "agent.completed" in report.event_stats["by_topic"]
    assert len(received) >= 4


def test_max_concurrency_zero_rejected():
    b = _diamond_nodes(GraphBuilder())
    compiled = b.compile()
    with pytest.raises(ValueError):
        GraphExecutor(compiled, max_concurrency=0)
