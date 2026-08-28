"""Mutable graph builder.

The builder lets callers register nodes and edges step by step. It does not
execute any agent. :meth:`compile` validates the topology and returns an
immutable :class:`CompiledGraph`.
"""

from __future__ import annotations

from typing import Callable, Optional

from magent.core.agent import BaseAgent

from .errors import GraphValidationError
from .model import CompiledGraph, END


class GraphBuilder:
    def __init__(self) -> None:
        self._nodes: dict[str, BaseAgent] = {}
        self._entry: Optional[str] = None
        self._edges: dict[str, str] = {}
        self._conditional: dict[str, tuple[Callable, dict[str, str]]] = {}
        self._parallel: dict[str, list[str]] = {}
        self._joins: dict[str, list[str]] = {}

    def add_node(self, node_id: str, agent: BaseAgent) -> "GraphBuilder":
        if not node_id:
            raise GraphValidationError("node_id must be non-empty")
        if node_id in self._nodes:
            raise GraphValidationError("duplicate node", node_id=node_id)
        if not isinstance(agent, BaseAgent):
            raise GraphValidationError("agent must be a BaseAgent", node_id=node_id)
        self._nodes[node_id] = agent
        return self

    def set_entry_point(self, node_id: str) -> "GraphBuilder":
        self._entry = node_id
        return self

    def add_edge(self, source: str, target: str) -> "GraphBuilder":
        if source in self._conditional or source in self._parallel:
            raise GraphValidationError(
                "node already has conditional/parallel edges", source=source
            )
        if source in self._edges:
            raise GraphValidationError("multiple unconditional edges", source=source)
        self._edges[source] = target
        return self

    def add_conditional_edges(
        self, source: str, router: Callable, mapping: dict[str, str]
    ) -> "GraphBuilder":
        if source in self._edges or source in self._parallel:
            raise GraphValidationError(
                "node already has an unconditional/parallel edge", source=source
            )
        if source in self._conditional:
            raise GraphValidationError("multiple conditional edges", source=source)
        if not isinstance(mapping, dict) or not mapping:
            raise GraphValidationError("mapping must be a non-empty dict", source=source)
        self._conditional[source] = (router, dict(mapping))
        return self

    def add_parallel_edges(self, source: str, targets: list[str]) -> "GraphBuilder":
        if not targets:
            raise GraphValidationError("parallel targets must be non-empty", source=source)
        if source in self._edges or source in self._conditional:
            raise GraphValidationError(
                "node already has unconditional/conditional edges", source=source
            )
        if source in self._parallel:
            raise GraphValidationError("multiple parallel fan-outs", source=source)
        for target in targets:
            if target == END or target not in self._nodes:
                raise GraphValidationError(
                    "parallel target must be a registered node", source=source, target=target
                )
        self._parallel[source] = list(targets)
        return self

    def add_join(self, node_id: str, parents: list[str]) -> "GraphBuilder":
        if not parents:
            raise GraphValidationError("join parents must be non-empty", node_id=node_id)
        if node_id not in self._nodes:
            raise GraphValidationError("join node not found", node_id=node_id)
        for parent in parents:
            if parent not in self._nodes:
                raise GraphValidationError(
                    "join parent not found", node_id=node_id, parent=parent
                )
        self._joins[node_id] = list(parents)
        return self

    def compile(self, name: str | None = None) -> CompiledGraph:
        from .validator import validate_graph

        validate_graph(
            nodes=self._nodes,
            edges=self._edges,
            conditional=self._conditional,
            parallel=self._parallel,
            joins=self._joins,
            entry=self._entry,
        )
        assert self._entry is not None
        return CompiledGraph(
            nodes=dict(self._nodes),
            edges=dict(self._edges),
            conditional={k: (r, dict(m)) for k, (r, m) in self._conditional.items()},
            parallel={k: list(v) for k, v in self._parallel.items()},
            joins={k: list(v) for k, v in self._joins.items()},
            entry=self._entry,
            name=name,
        )
