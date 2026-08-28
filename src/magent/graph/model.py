"""Compiled, immutable graph topology.

A ``CompiledGraph`` is produced by :meth:`GraphBuilder.compile` and is never
mutated by the executor. Because ``compile`` copies the topology, later
mutations of the originating builder do not affect an already compiled graph.
"""

from __future__ import annotations

from typing import Callable

from magent.core.agent import BaseAgent

END = "__end__"


class CompiledGraph:
    """An immutable, validated graph ready to be executed.

    Attributes:
        nodes: ``node_id -> BaseAgent``.
        edges: ``source -> target`` for unconditional edges.
        conditional: ``source -> (router, mapping)`` for conditional edges.
        entry: The single entry node id.
        name: Optional graph name (for reports).
    """

    def __init__(
        self,
        nodes: dict[str, BaseAgent],
        edges: dict[str, str],
        conditional: dict[str, tuple[Callable, dict[str, str]]],
        entry: str,
        name: str | None = None,
    ) -> None:
        self._nodes = dict(nodes)
        self._edges = dict(edges)
        self._conditional = {k: (r, dict(m)) for k, (r, m) in conditional.items()}
        self._entry = entry
        self._name = name

    @property
    def nodes(self) -> dict[str, BaseAgent]:
        return self._nodes

    @property
    def edges(self) -> dict[str, str]:
        return self._edges

    @property
    def conditional(self) -> dict[str, tuple[Callable, dict[str, str]]]:
        return self._conditional

    @property
    def entry(self) -> str:
        return self._entry

    @property
    def name(self) -> str | None:
        return self._name

    async def run(self, initial_state, *, run_id: str | None = None, clock=None):
        """Execute this graph; see :class:`GraphExecutor` for semantics."""
        from .executor import GraphExecutor

        return await GraphExecutor(self, run_id=run_id, clock=clock).run(initial_state)
