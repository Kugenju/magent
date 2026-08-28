from __future__ import annotations

import pytest
from pydantic import BaseModel

from magent import AgentResult, BaseAgent, END, ExecutionStatus, GraphBuilder

END = "__end__"


class State(BaseModel):
    value: int = 0
    visited: list[str] = []


class Increment(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(
            updates={"value": state.value + 1, "visited": state.visited + [runtime.agent_name]}
        )


class Branch(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"visited": state.visited + [runtime.agent_name]})


async def test_linear_graph_executes_in_order():
    graph = (
        GraphBuilder()
        .add_node("a", Increment("a"))
        .add_node("b", Increment("b"))
        .add_node("c", Increment("c"))
        .set_entry_point("a")
        .add_edge("a", "b")
        .add_edge("b", "c")
        .add_edge("c", END)
        .compile()
    )
    state, report = await graph.run(State())
    assert state.value == 3
    assert state.visited == ["a", "b", "c"]
    assert report.success
    assert [s.node_id for s in report.steps] == ["a", "b", "c"]


def _route(state: State) -> str:
    return "left" if state.value >= 1 else "right"


def _build_conditional() -> "object":
    return (
        GraphBuilder()
        .add_node("start", Increment("start"))
        .add_node("left", Branch("left"))
        .add_node("right", Branch("right"))
        .set_entry_point("start")
        .add_conditional_edges("start", _route, {"left": "left", "right": "right"})
        .add_edge("left", END)
        .add_edge("right", END)
        .compile()
    )


async def test_conditional_takes_selected_branch_only():
    state, report = await _build_conditional().run(State())
    assert state.visited == ["start", "left"]
    statuses = {s.node_id: s.status for s in report.steps}
    assert statuses["left"] == ExecutionStatus.SUCCESS
    assert statuses["right"] == ExecutionStatus.NOT_EXECUTED


async def test_router_sees_updated_state():
    state, _ = await _build_conditional().run(State())
    assert state.value == 1  # start incremented, so router picks "left"


class Zero(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"visited": state.visited + ["start"]})


async def test_conditional_other_branch_when_false():
    graph = (
        GraphBuilder()
        .add_node("start", Zero("start"))
        .add_node("left", Branch("left"))
        .add_node("right", Branch("right"))
        .set_entry_point("start")
        .add_conditional_edges("start", _route, {"left": "left", "right": "right"})
        .add_edge("left", END)
        .add_edge("right", END)
        .compile()
    )
    state, report = await graph.run(State())
    assert state.visited == ["start", "right"]
    statuses = {s.node_id: s.status for s in report.steps}
    assert statuses["right"] == ExecutionStatus.SUCCESS
    assert statuses["left"] == ExecutionStatus.NOT_EXECUTED


class Boomer(BaseAgent):
    async def run(self, state, runtime):
        raise RuntimeError("boom")


async def test_agent_failure_stops_graph():
    graph = (
        GraphBuilder()
        .add_node("a", Boomer("a"))
        .add_node("b", Increment("b"))
        .set_entry_point("a")
        .add_edge("a", "b")
        .add_edge("b", END)
        .compile()
    )
    state, report = await graph.run(State())
    assert report.success is False
    statuses = {s.node_id: s.status for s in report.steps}
    assert statuses["a"] == ExecutionStatus.FAILED
    assert statuses["b"] == ExecutionStatus.NOT_EXECUTED
    assert state.value == 0


class NoOp(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult()


def _route_bad(state):
    raise RuntimeError("router boom")


async def test_router_exception_fails():
    graph = (
        GraphBuilder()
        .add_node("a", NoOp("a"))
        .add_node("b", Increment("b"))
        .set_entry_point("a")
        .add_conditional_edges("a", _route_bad, {"x": "b", "y": END})
        .add_edge("b", END)
        .compile()
    )
    state, report = await graph.run(State())
    assert report.success is False
    routing_failures = [s for s in report.steps if s.error and s.error.get("type") == "GraphRoutingError"]
    assert routing_failures


def _route_unknown(state):
    return "nope"


async def test_router_unknown_label_fails():
    graph = (
        GraphBuilder()
        .add_node("a", NoOp("a"))
        .add_node("b", Increment("b"))
        .set_entry_point("a")
        .add_conditional_edges("a", _route_unknown, {"x": "b", "y": END})
        .add_edge("b", END)
        .compile()
    )
    state, report = await graph.run(State())
    assert report.success is False
    routing_failures = [s for s in report.steps if s.error and s.error.get("type") == "GraphRoutingError"]
    assert routing_failures
