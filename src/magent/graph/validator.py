"""Compile-time graph validation.

``validate_graph`` enforces every rule from PHASE2/PHASE3 before a graph is
executed: node/edge existence, out-edge exclusivity, parallel/join consistency,
reachability from the entry point, cycle (and self-reference) detection, that
every parallel branch reaches a join, and that every reachable path eventually
reaches ``END``.
"""

from __future__ import annotations

from .errors import GraphValidationError
from .model import END


def validate_graph(
    *,
    nodes: dict,
    edges: dict,
    conditional: dict,
    parallel: dict,
    joins: dict,
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

    for source, targets in parallel.items():
        if source not in nodes:
            raise GraphValidationError("parallel source not found", source=source)
        for target in targets:
            if target == END or target not in nodes:
                raise GraphValidationError(
                    "parallel target must be a node", source=source, target=target
                )

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

    for join_node, parents in joins.items():
        if join_node not in nodes:
            raise GraphValidationError("join node not found", node_id=join_node)
        if not parents:
            raise GraphValidationError("join has no parents", node_id=join_node)
        for parent in parents:
            if parent not in nodes:
                raise GraphValidationError(
                    "join parent not found", node_id=join_node, parent=parent
                )

    # Out-edge exclusivity: a node may have at most one kind of outgoing edge.
    for node in nodes:
        kinds = sum(
            [
                1 if node in edges else 0,
                1 if node in parallel else 0,
                1 if node in conditional else 0,
            ]
        )
        if kinds > 1:
            raise GraphValidationError(
                "node has multiple outgoing edge kinds", source=node
            )

    # Predecessor sets.
    preds: dict[str, set] = {n: set() for n in nodes}
    for source, target in edges.items():
        if target != END:
            preds[target].add(source)
    for source, targets in parallel.items():
        for target in targets:
            if target != END:
                preds[target].add(source)
    for source, (router, mapping) in conditional.items():
        for target in mapping.values():
            if target != END:
                preds[target].add(source)
    for join_node, parents in joins.items():
        for parent in parents:
            if parent != END:
                preds[join_node].add(parent)

    conditional_targets: set[str] = set()
    for source, (router, mapping) in conditional.items():
        for target in mapping.values():
            if target != END:
                conditional_targets.add(target)

    # Join consistency: the incoming edges of a join must equal its parents,
    # and a join cannot be a conditional target.
    for join_node, parents in joins.items():
        if set(parents) != preds[join_node]:
            raise GraphValidationError(
                "join parents do not match incoming edges", node_id=join_node
            )
        if join_node in conditional_targets:
            raise GraphValidationError(
                "join node cannot be a conditional target", node_id=join_node
            )

    # Non-join nodes may have at most one predecessor.
    for node in nodes:
        if node in joins:
            continue
        if len(preds[node]) > 1:
            raise GraphValidationError(
                "node has multiple predecessors; use add_join", node_id=node
            )

    _check_connectivity(nodes, edges, parallel, conditional, joins, entry)


def _succs(node: str, edges, parallel, conditional, joins) -> list[str]:
    out: list[str] = []
    if node in edges and edges[node] != END:
        out.append(edges[node])
    if node in parallel:
        out.extend(t for t in parallel[node] if t != END)
    if node in conditional:
        out.extend(t for t in conditional[node][1].values() if t != END)
    for join_node, parents in joins.items():
        if node in parents:
            out.append(join_node)
    return out


def _check_connectivity(nodes, edges, parallel, conditional, joins, entry) -> None:
    # Cycle detection + reachability from entry.
    visited: set[str] = set()

    def _visit(node: str, stack: set[str]) -> None:
        if node == END:
            return
        if node in stack:
            raise GraphValidationError("cycle detected in graph", node_id=node)
        if node in visited:
            return
        stack.add(node)
        for nxt in _succs(node, edges, parallel, conditional, joins):
            _visit(nxt, stack)
        stack.discard(node)
        visited.add(node)

    _visit(entry, set())
    unreachable = set(nodes) - visited
    if unreachable:
        raise GraphValidationError(
            "node not reachable from entry", node_id=sorted(unreachable)[0]
        )

    # Every node must be able to reach END.
    end_memo: dict[str, bool] = {}

    def _reaches_end(node: str, stack: set[str]) -> bool:
        if node == END:
            return True
        if node in end_memo:
            return end_memo[node]
        if node in stack:
            return False
        stack.add(node)
        result = False
        if (
            (node in edges and edges[node] == END)
            or (node in parallel and END in parallel[node])
            or (node in conditional and END in conditional[node][1].values())
        ):
            result = True
        else:
            for nxt in _succs(node, edges, parallel, conditional, joins):
                if _reaches_end(nxt, stack):
                    result = True
                    break
        stack.discard(node)
        end_memo[node] = result
        return result

    for node in nodes:
        if not _reaches_end(node, set()):
            raise GraphValidationError("node cannot reach END", node_id=node)

    # Every parallel branch must reach a join.
    join_memo: dict[str, bool] = {}

    def _reaches_join(node: str, stack: set[str]) -> bool:
        if node in joins:
            return True
        if node in stack:
            return False
        if node in join_memo:
            return join_memo[node]
        stack.add(node)
        result = False
        for nxt in _succs(node, edges, parallel, conditional, joins):
            if _reaches_join(nxt, stack):
                result = True
                break
        stack.discard(node)
        join_memo[node] = result
        return result

    for source, targets in parallel.items():
        for target in targets:
            if not _reaches_join(target, set()):
                raise GraphValidationError(
                    "parallel branch does not reach a join", source=source, target=target
                )
