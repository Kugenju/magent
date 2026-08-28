"""Compile-time graph validation.

``validate_graph`` enforces every rule from PHASE2 before a graph is executed:
node/edge existence, out-edge exclusivity, reachability from the entry point,
cycle (and self-reference) detection, and the requirement that every reachable
path eventually reaches ``END``.
"""

from __future__ import annotations

from .errors import GraphValidationError
from .model import END


def validate_graph(
    *,
    nodes: dict,
    edges: dict,
    conditional: dict,
    entry: str | None,
) -> None:
    if not nodes:
        raise GraphValidationError("graph has no nodes")
    if entry is None:
        raise GraphValidationError("entry point not set")
    if entry not in nodes:
        raise GraphValidationError("entry point not found", node_id=entry)

    for source, target in edges.items():
        if source not in nodes:
            raise GraphValidationError("edge source not found", source=source)
        if target != END and target not in nodes:
            raise GraphValidationError("edge target not found", source=source, target=target)

    for source, (router, mapping) in conditional.items():
        if source not in nodes:
            raise GraphValidationError("conditional source not found", source=source)
        labels = list(mapping.keys())
        for label in labels:
            if not label:
                raise GraphValidationError("empty routing label", source=source)
        if len(labels) != len(set(labels)):
            raise GraphValidationError("duplicate routing labels", source=source)
        for label, target in mapping.items():
            if target != END and target not in nodes:
                raise GraphValidationError(
                    "conditional target not found", source=source, target=target
                )

    for source in nodes:
        if source in edges and source in conditional:
            raise GraphValidationError(
                "node mixes unconditional and conditional edges", source=source
            )

    visited: set[str] = set()
    _visit(entry, nodes, edges, conditional, visited, set())

    unreachable = set(nodes) - visited
    if unreachable:
        raise GraphValidationError(
            "node not reachable from entry", node_id=sorted(unreachable)[0]
        )


def _visit(node: str, nodes: dict, edges: dict, conditional: dict, visited: set, stack: set) -> None:
    if node == END:
        return
    if node in stack:
        raise GraphValidationError("cycle detected in graph", node_id=node)
    if node in visited:
        return
    stack.add(node)
    if node in edges:
        _visit(edges[node], nodes, edges, conditional, visited, stack)
    elif node in conditional:
        for target in conditional[node][1].values():
            _visit(target, nodes, edges, conditional, visited, stack)
    else:
        raise GraphValidationError(
            "node has no outgoing edge (cannot reach END)", node_id=node
        )
    stack.discard(node)
    visited.add(node)
