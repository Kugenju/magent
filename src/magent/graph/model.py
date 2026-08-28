"""Compiled, immutable graph topology.

A ``CompiledGraph`` is produced by :meth:`GraphBuilder.compile`. The executor
reads it but never mutates it. Because ``compile`` copies the topology and the
public properties return read-only proxies, later mutations of the originating
builder do not affect an already compiled graph (phase-2 closure item).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Callable

from magent.core.agent import BaseAgent

END = "__end__"


class CompiledGraph:
    """An immutable, validated graph ready to be executed.

    Attributes:
        nodes: ``node_id -> BaseAgent``.
        edges: ``source -> target`` for unconditional edges.
        conditional: ``source -> (router, mapping)`` for conditional edges.
        parallel: ``source -> (target, ...)`` for fan-out edges.
        joins: ``join_node -> (parent, ...)`` for fan-in parents.
        entry: The single entry node id.
        name: Optional graph name (for reports).
    """

    def __init__(
        self,
        *,
        nodes: dict[str, BaseAgent],
        edges: dict[str, str],
        conditional: dict[str, tuple[Callable, dict[str, str]]],
        parallel: dict[str, list[str]],
        joins: dict[str, list[str]],
        entry: str,
        name: str | None = None,
    ) -> None:
        self._nodes = dict(nodes)
        self._edges = dict(edges)
        self._conditional = {k: (r, dict(m)) for k, (r, m) in conditional.items()}
        self._parallel = {k: list(v) for k, v in parallel.items()}
        self._joins = {k: list(v) for k, v in joins.items()}
        self._entry = entry
        self._name = name

    @property
    def nodes(self) -> MappingProxyType:
        return MappingProxyType(self._nodes)

    @property
    def edges(self) -> MappingProxyType:
        return MappingProxyType(self._edges)

    @property
    def conditional(self) -> MappingProxyType:
        return MappingProxyType(
            {k: (r, MappingProxyType(m)) for k, (r, m) in self._conditional.items()}
        )

    @property
    def parallel(self) -> MappingProxyType:
        return MappingProxyType({k: tuple(v) for k, v in self._parallel.items()})

    @property
    def joins(self) -> MappingProxyType:
        return MappingProxyType({k: tuple(v) for k, v in self._joins.items()})

    @property
    def entry(self) -> str:
        return self._entry

    @property
    def name(self) -> str | None:
        return self._name

    async def run(
        self,
        initial_state,
        *,
        run_id: str | None = None,
        clock=None,
        max_concurrency: int | None = None,
        event_bus=None,
    ):
        """Execute this graph; see :class:`GraphExecutor` for semantics."""
        from .executor import GraphExecutor

        return await GraphExecutor(
            self,
            run_id=run_id,
            clock=clock,
            max_concurrency=max_concurrency,
            event_bus=event_bus,
        ).run(initial_state)
