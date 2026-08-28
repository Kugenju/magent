"""Tests for fan-out / fan-in topology, branch isolation and concurrency (phase 3)."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from magent import (
    AgentResult,
    BaseAgent,
    END,
    ExecutionStatus,
    GraphBuilder,
    GraphValidationError,
)

END = "__end__"


class _Noop(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult()


class Counter:
    def __init__(self) -> None:
        self.current = 0
        self.peak = 0


class CounterAgent(BaseAgent):
    def __init__(self, name: str, counter: Counter, delay: float = 0.02) -> None:
        super().__init__(name)
        self.counter = counter
        self.delay = delay

    async def run(self, state, runtime):
        self.counter.current += 1
        self.counter.peak = max(self.counter.peak, self.counter.current)
        try:
            await asyncio.sleep(self.delay)
            return AgentResult()
        finally:
            self.counter.current -= 1


class SetValue(BaseAgent):
    def __init__(self, name: str, updates: dict) -> None:
        super().__init__(name)
        self.updates = updates

    async def run(self, state, runtime):
        return AgentResult(updates=self.updates)


class ReadValue(BaseAgent):
    def __init__(self, name: str, read_field: str, write_field: str) -> None:
        super().__init__(name)
        self.read_field = read_field
        self.write_field = write_field

    async def run(self, state, runtime):
        return AgentResult(updates={self.write_field: getattr(state, self.read_field)})


def _wire_diamond(builder: GraphBuilder) -> GraphBuilder:
    """Wire a->[b,c]->d->END. Nodes must already be registered."""
    return (
        builder.set_entry_point("a")
        .add_parallel_edges("a", ["b", "c"])
        .add_edge("b", "d")
        .add_edge("c", "d")
        .add_join("d", ["b", "c"])
        .add_edge("d", END)
    )


class IsoState(BaseModel):
    value: int = 0
    c: int = 0


class MarkState(BaseModel):
    b_seen: str = ""
    c_seen: str = ""


async def test_fan_out_fan_in_executes_all_branches():
    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    b.add_node("b", SetValue("b", {"b_seen": "B"}))
    b.add_node("c", SetValue("c", {"c_seen": "C"}))
    b.add_node("d", _Noop("d"))
    _wire_diamond(b)
    state, report = await b.compile().run(MarkState())
    assert report.success
    assert state.b_seen == "B" and state.c_seen == "C"
    statuses = {s.node_id: s.status for s in report.steps}
    assert statuses == {
        "a": ExecutionStatus.SUCCESS,
        "b": ExecutionStatus.SUCCESS,
        "c": ExecutionStatus.SUCCESS,
        "d": ExecutionStatus.SUCCESS,
    }


async def test_two_independent_agents_actually_overlap():
    counter = Counter()
    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    b.add_node("b", CounterAgent("b", counter))
    b.add_node("c", CounterAgent("c", counter))
    b.add_node("d", _Noop("d"))
    _wire_diamond(b)
    await b.compile().run(MarkState())
    assert counter.peak == 2


async def test_max_concurrency_one_is_serial():
    counter = Counter()
    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    b.add_node("b", CounterAgent("b", counter))
    b.add_node("c", CounterAgent("c", counter))
    b.add_node("d", _Noop("d"))
    _wire_diamond(b)
    await b.compile().run(MarkState(), max_concurrency=1)
    assert counter.peak == 1


async def test_concurrency_never_exceeds_limit():
    counter = Counter()

    class MultiState(BaseModel):
        pass

    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    for n in ("b", "c", "e"):
        b.add_node(n, CounterAgent(n, counter))
    b.add_node("d", _Noop("d"))
    (
        b.set_entry_point("a")
        .add_parallel_edges("a", ["b", "c", "e"])
        .add_edge("b", "d")
        .add_edge("c", "d")
        .add_edge("e", "d")
        .add_join("d", ["b", "c", "e"])
        .add_edge("d", END)
    )
    await b.compile().run(MultiState(), max_concurrency=2)
    assert counter.peak <= 2


async def test_branch_reads_only_entry_snapshot():
    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    # B mutates value; C reads value into c. Isolation => C sees snapshot (0).
    b.add_node("b", SetValue("b", {"value": 10}))
    b.add_node("c", ReadValue("c", "value", "c"))
    b.add_node("d", _Noop("d"))
    _wire_diamond(b)
    state, report = await b.compile().run(IsoState())
    assert report.success
    assert state.value == 10
    assert state.c == 0


async def test_each_branch_executes_exactly_once():
    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    b.add_node("b", SetValue("b", {"b_seen": "B"}))
    b.add_node("c", SetValue("c", {"c_seen": "C"}))
    b.add_node("d", _Noop("d"))
    _wire_diamond(b)
    _, report = await b.compile().run(MarkState())
    node_ids = [s.node_id for s in report.steps]
    assert sorted(node_ids) == ["a", "b", "c", "d"]
    assert len(node_ids) == len(set(node_ids))


async def test_compiled_graph_immutable_after_compile():
    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    b.add_node("b", _Noop("b"))
    b.add_node("c", _Noop("c"))
    b.add_node("d", _Noop("d"))
    _wire_diamond(b)
    compiled = b.compile()
    b._parallel["a"].append("z")  # mutate builder after compile
    assert "z" not in compiled.parallel["a"]


def test_parallel_with_unknown_target_rejected():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", _Noop("a")).set_entry_point("a").add_parallel_edges(
            "a", ["ghost"]
        )


def test_join_with_unknown_parent_rejected():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", _Noop("a")).set_entry_point("a").add_join("a", ["ghost"])


def test_parallel_branch_must_reach_join():
    b = GraphBuilder()
    b.add_node("a", _Noop("a")).set_entry_point("a")
    b.add_node("b", _Noop("b"))
    b.add_parallel_edges("a", ["b"])
    b.add_edge("b", END)
    with pytest.raises(GraphValidationError):
        b.compile()


def test_join_parents_must_match_incoming_edges():
    b = GraphBuilder()
    b.add_node("a", _Noop("a")).set_entry_point("a")
    b.add_node("b", _Noop("b")).add_edge("a", "b")
    b.add_node("d", _Noop("d"))
    b.add_edge("b", "d")
    b.add_join("d", ["a", "b"])  # "a" is not an incoming edge of d
    with pytest.raises(GraphValidationError):
        b.compile()
