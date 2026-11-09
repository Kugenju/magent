"""Deterministic in-memory MCP server and transport for offline testing (phase 10).

This is the MCP-side mirror of the LLM module's ``FakeProvider``: zero network,
zero SDK imports, fully deterministic behaviour. It lets the *entire* phase-10
policy pipeline (loader -> registry -> proxy) be exercised offline, and it is
the only transport the default (offline) test suite uses.

Failure injection is explicit and scriptable: handlers return
``fake_outcome(...)`` results (a tool-level failure uses ``is_error=True``)
or raise ``McpToolError`` subclasses (transport/protocol-level failures).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from magent.tools.models import ToolError

from .errors import build_tool_error
from .spec import McpToolDescriptor
from .transport import McpCallOutcome, ProgressCallback

HandlerFn = Callable[[dict[str, Any]], Any]  # sync or async, returns McpCallOutcome


def fake_outcome(
    *,
    text: Sequence[str] | str = (),
    structured: dict[str, Any] | None = None,
    is_error: bool = False,
    error_kind: str | None = None,
    error_message: str | None = None,
    raw_meta: Mapping[str, Any] | None = None,
) -> McpCallOutcome:
    """Convenience builder for handler return values."""
    if isinstance(text, str):
        text = (text,)
    return McpCallOutcome(
        content_text=tuple(text),
        structured=dict(structured) if structured is not None else None,
        is_error=is_error,
        error_kind=error_kind,
        error_message=error_message,
        raw_meta=dict(raw_meta) if raw_meta is not None else {},
    )


@dataclass(frozen=True)
class FakeToolDefinition:
    """One tool served by :class:`FakeMcpServer`.

    ``handler(args) -> McpCallOutcome`` (sync or async) implements the tool.
    Annotation hints live on ``read_only`` / ``idempotent`` / ``destructive``;
    ``elicited=True`` simulates a server requesting interactive elicitation
    (the adapter denies it by default, per phase-10 policy).
    """

    name: str
    handler: HandlerFn
    description: str = ""
    input_schema: Mapping[str, Any] | None = None
    output_schema: Mapping[str, Any] | None = None
    read_only: bool | None = None
    idempotent: bool | None = None
    destructive: bool | None = None
    elicited: bool = False

    def to_descriptor(self) -> McpToolDescriptor:
        return McpToolDescriptor(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema if self.input_schema is None else dict(self.input_schema),
            output_schema=self.output_schema if self.output_schema is None else dict(self.output_schema),
            read_only_hint=self.read_only,
            idempotent_hint=self.idempotent,
            destructive_hint=self.destructive,
        )


class FakeMcpServer:
    """Deterministic scriptable MCP server (no process, no socket)."""

    version = "fake"

    def __init__(self, name: str, tools: Sequence[FakeToolDefinition]) -> None:
        self.name = name
        self._tools: dict[str, FakeToolDefinition] = {}
        for tool in tools:
            if not tool.name or tool.name in self._tools:
                raise ToolError(
                    "mcp.fake",
                    "",
                    f"duplicate or empty fake tool name {tool.name!r}",
                )
            self._tools[tool.name] = tool
        # Granular telemetry for tests (ordered, deterministic).
        self.call_log: list[tuple[str, dict[str, Any]]] = []
        self.list_log_count = 0
        self.progress_emits: list[tuple[str, dict[str, Any]]] = []

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def get_definition(self, name: str) -> FakeToolDefinition:
        tool = self._tools.get(name)
        if tool is None:
            raise build_tool_error(
                "invalid",
                f"mcp.fake:{self.name}",
                "",
                f"unknown tool {name!r}",
            )
        return tool


class InMemoryMcpTransport:
    """Transport that speaks directly to a :class:`FakeMcpServer` in-process."""

    def __init__(self, server: FakeMcpServer) -> None:
        self._server = server
        self._connected = False
        self._inflight: set[str] = set()

    async def connect(self) -> None:
        self._connected = True

    async def list_tools(self) -> list[McpToolDescriptor]:
        if not self._connected:
            raise build_tool_error(
                "permanent",
                f"mcp.fake:{self._server.name}",
                "",
                "transport is not connected",
            )
        self._server.list_log_count += 1
        return [
            self._server.get_definition(n).to_descriptor()
            for n in self._server.tool_names
        ]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> McpCallOutcome:
        if not self._connected:
            raise build_tool_error(
                "permanent",
                f"mcp.fake:{self._server.name}",
                "",
                "transport is not connected",
            )
        definition = self._server.get_definition(tool_name)
        self._inflight.add(tool_name)
        try:
            self._server.call_log.append((tool_name, dict(arguments)))
            if definition.elicited:
                # Phase-10 policy: no client-side human-in-the-loop channel.
                # A denial is a tool-level failure: is_error outcome, not a
                # transport exception, so agents get one uniform result shape.
                self._inflight.discard(tool_name)
                return fake_outcome(
                    is_error=True,
                    error_kind="elicitation_denied",
                    error_message=(
                        f"server {self._server.name!r} requested elicitation for "
                        f"tool {tool_name!r}; denied by default"
                    ),
                )
            if on_progress is not None:
                for step in range(2):
                    payload = {"progress": step, "total": 2}
                    self._server.progress_emits.append((tool_name, payload))
                    on_progress(payload)
            result = definition.handler(dict(arguments))
            if hasattr(result, "__await__"):
                result = await result  # type: ignore[union-attr]
            if not isinstance(result, McpCallOutcome):
                raise build_tool_error(
                    "permanent",
                    f"mcp.fake:{self._server.name}",
                    "",
                    f"handler for {tool_name!r} must return McpCallOutcome",
                )
            return result
        finally:
            self._inflight.discard(tool_name)

    async def cancel_pending(self, tool_name: str) -> None:
        self._inflight.discard(tool_name)

    async def close(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def inflight(self) -> frozenset[str]:
        return frozenset(self._inflight)


class FakeTransportFactory:
    """``McpServerConfig.factory`` returning a fresh transport per load.

    ``load_count`` and ``transports`` are deterministic assertions points for
    tests; the loader opens exactly one transport per configured server.
    """

    def __init__(self, server: FakeMcpServer) -> None:
        self.server = server
        self.load_count = 0
        self.transports: list[InMemoryMcpTransport] = []

    def __call__(self) -> InMemoryMcpTransport:
        transport = InMemoryMcpTransport(self.server)
        self.load_count += 1
        self.transports.append(transport)
        return transport
