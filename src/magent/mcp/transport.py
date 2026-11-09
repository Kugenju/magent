"""Transport seam between magent and MCP SDKs (phase 10).

The SDK types never appear in these protocols: transports normalize listings
into :class:`McpToolDescriptor` and call results into the bounded
:class:`McpCallOutcome`. Swapping SDK versions (v1 -> v2) must only touch
transport implementations, never the proxy/loader/registry chain.

Transport implementations are the only L2 network surface of the MCP module
(see ``docs/architecture/NETWORK_POLICY.md``): they must import SDK libraries
lazily inside functions, honor timeouts/cancellation, and raise classified
:class:`McpToolError` subclasses from ``magent.mcp.errors``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from magent.tools.models import ToolError

from .spec import McpToolDescriptor

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class McpCallOutcome:
    """Bounded, SDK-agnostic result of one ``tools/call``.

    ``structured`` mirrors the MCP structuredContent object (may be ``None``);
    ``content_text`` holds concatenated text content blocks. A server-side tool
    failure is expressed with ``is_error=True`` plus ``error_kind``/``message``,
    not by raising: raising is reserved for transport/protocol failures.
    """

    content_text: tuple[str, ...] = ()
    structured: dict[str, Any] | None = None
    is_error: bool = False
    error_kind: str | None = None
    error_message: str | None = None
    raw_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(self.content_text)


@runtime_checkable
class McpTransport(Protocol):
    """Minimal transport contract (connect/list/call/cancel/close)."""

    async def connect(self) -> None:
        """Establish the underlying session; must be idempotent per loader load."""
        ...

    async def list_tools(self) -> list[McpToolDescriptor]:
        """Return the server's tool descriptors in a deterministic order."""
        ...

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> McpCallOutcome:
        """Invoke ``tools/call``; raise classified errors for transport failures."""
        ...

    async def cancel_pending(self, tool_name: str) -> None:
        """Best-effort cancellation notification for an in-flight call."""
        ...

    async def close(self) -> None:
        """Release the session; must be safe to call twice."""
        ...
