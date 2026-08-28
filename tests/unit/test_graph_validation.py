from __future__ import annotations

import pytest

from magent import AgentResult, BaseAgent, END, GraphBuilder, GraphValidationError


class Dummy(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult()


def test_empty_graph_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().compile()


def test_missing_entry_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).add_edge("a", END).compile()


def test_unknown_edge_source_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).set_entry_point("a").add_edge(
            "missing", END
        ).compile()


def test_unknown_edge_target_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).set_entry_point("a").add_edge(
            "a", "ghost"
        ).compile()


def test_unreachable_node_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).add_node("b", Dummy("b")).set_entry_point(
            "a"
        ).add_edge("a", END).compile()


def test_cycle_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).add_node("b", Dummy("b")).set_entry_point(
            "a"
        ).add_edge("a", "b").add_edge("b", "a").compile()


def test_self_loop_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).set_entry_point("a").add_edge(
            "a", "a"
        ).compile()


def test_mixed_edges_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).add_node("b", Dummy("b")).set_entry_point(
            "a"
        ).add_edge("a", "b").add_conditional_edges(
            "a", lambda s: "x", {"x": END}
        ).compile()


def test_multiple_unconditional_edges_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).add_node("b", Dummy("b")).add_node(
            "c", Dummy("c")
        ).set_entry_point("a").add_edge("a", "b").add_edge("a", "c").compile()


def test_path_without_end_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).add_node("b", Dummy("b")).set_entry_point(
            "a"
        ).add_edge("a", "b").compile()


def test_empty_routing_label_fails():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).set_entry_point("a").add_conditional_edges(
            "a", lambda s: "", {"": END}
        ).compile()
