"""Tests for parallel-branch state merge and reducer conflict (phase 3, §5/§10)."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from magent import (
    AgentResult,
    BaseAgent,
    END,
    ExecutionStatus,
    GraphBuilder,
    StateMergeConflictError,
)


class _Noop(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult()


class TraceState(BaseModel):
    trace: list[str] = []
    reducers: ClassVar[dict] = {"trace": lambda cur, new: cur + new}


class SumState(BaseModel):
    total: int = 0
    reducers: ClassVar[dict] = {"total": lambda cur, new: cur + new}


class PlainState(BaseModel):
    x: int = 0
    y: int = 0


class AppendAgent(BaseAgent):
    def __init__(self, name: str, tag: str) -> None:
        super().__init__(name)
        self.tag = tag

    async def run(self, state, runtime):
        return AgentResult(updates={"trace": [self.tag]})


class AddAgent(BaseAgent):
    def __init__(self, name: str, amount: int) -> None:
        super().__init__(name)
        self.amount = amount

    async def run(self, state, runtime):
        return AgentResult(updates={"total": self.amount})


class WriteX(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"x": 1})


class WriteY(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"y": 2})


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


def _build_trace():
    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    b.add_node("b", AppendAgent("b", "B"))
    b.add_node("c", AppendAgent("c", "C"))
    b.add_node("d", _Noop("d"))
    _wire_diamond(b)
    return b.compile()


async def test_reducer_combines_parallel_branches():
    state, report = await _build_trace().run(TraceState())
    assert report.success
    assert set(state.trace) == {"B", "C"}
    assert len(state.trace) == 2


async def test_reducer_order_is_independent():
    for _ in range(10):
        state, _ = await _build_trace().run(TraceState())
        assert sorted(state.trace) == ["B", "C"]


async def test_reducer_handles_base_and_duplicate_values():
    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    b.add_node("b", AddAgent("b", 5))
    b.add_node("c", AddAgent("c", 7))
    b.add_node("d", _Noop("d"))
    _wire_diamond(b)
    state, report = await b.compile().run(SumState())
    assert report.success
    assert state.total == 12


async def test_conflict_without_reducer_fails():
    b = GraphBuilder()
    b.add_node("a", _Noop("a"))
    b.add_node("b", WriteX("b"))  # x = 1
    b.add_node("c", WriteX("c"))  # x = 1 again -> conflict
    b.add_node("d", _Noop("d"))
    _wire_diamond(b)
    state, report = await b.compile().run(PlainState())
    assert report.success is False
    conflicts = [
        s
        for s in report.steps
        if s.error and s.error.get("type") == "StateMergeConflictError"
    ]
    assert conflicts
    assert isinstance(StateMergeConflictError("x"), Exception)
