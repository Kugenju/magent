from __future__ import annotations

import pytest

from magent import AgentResult, BaseAgent, CompiledGraph, GraphBuilder, GraphValidationError

END = "__end__"


class Dummy(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult()


def test_add_node_and_compile_returns_compiled_graph():
    graph = (
        GraphBuilder()
        .add_node("a", Dummy("a"))
        .set_entry_point("a")
        .add_edge("a", END)
        .compile()
    )
    assert isinstance(graph, CompiledGraph)


def test_duplicate_node_raises():
    with pytest.raises(GraphValidationError):
        GraphBuilder().add_node("a", Dummy("a")).add_node("a", Dummy("a"))


def test_compiled_graph_is_immutable_to_builder_changes():
    builder = (
        GraphBuilder().add_node("a", Dummy("a")).set_entry_point("a").add_edge("a", END)
    )
    compiled = builder.compile()
    builder.add_node("b", Dummy("b"))  # mutate builder after compile
    assert "b" not in compiled.nodes
