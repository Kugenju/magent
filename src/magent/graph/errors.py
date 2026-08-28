"""Graph-specific validation errors."""

from __future__ import annotations

from magent.core.errors import MagentError


class GraphValidationError(MagentError):
    """Raised when a graph topology is invalid at build or compile time.

    Carries the offending ``node_id`` / ``source`` / ``target`` when known, so
    downstream tooling can point the user at the exact problem edge or node.
    """

    def __init__(
        self,
        reason: str,
        *,
        node_id: str | None = None,
        source: str | None = None,
        target: str | None = None,
        parent: str | None = None,
    ) -> None:
        self.reason = reason
        self.node_id = node_id
        self.source = source
        self.target = target
        self.parent = parent
        message = reason
        if node_id is not None:
            message += f" (node={node_id})"
        if source is not None:
            message += f" (source={source})"
        if target is not None:
            message += f" (target={target})"
        if parent is not None:
            message += f" (parent={parent})"
        super().__init__(message)
