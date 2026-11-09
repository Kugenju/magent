"""Real stdio transport (P10.2) — official MCP SDK wiring, lazily imported.

This is the module-checked real path of P10.2: a local MCP server process is
spawned over stdio and driven with the official SDK (``mcp>=1.10,<2``,
extras ``magent[mcp]``). The *seam* stayed SDK-free (``McpTransport`` /
``McpCallOutcome`` / ``McpToolDescriptor``) — this module is the only place
where SDK types live, and every import of the SDK happens lazily inside
functions so the core (and the default offline test gate) stays SDK-free.

Policy inside the transport (phase-10 contract):

- magent's per-call timeout is the hard wall (``call_tool`` passes no extra
  read timeout to the SDK; the proxy arms ``asyncio.wait_for`` around it);
- progress notifications flow through the SDK callback into the proxy's
  ``on_progress`` hook (sync, non-blocking);
- cancellation: cancelling the awaiting coroutine cancels the in-flight
  request inside the SDK's anyio scope; ``cancel_pending`` stays a no-op
  notification point for future protocol-level cancellation;
- every SDK-level exception is normalized via
  :func:`magent.mcp.errors.map_transport_exception` (classified, never raw).
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence, TextIO

from magent.mcp.errors import McpInvalidConfigError, McpPermanentError, map_transport_exception
from magent.mcp.spec import McpToolDescriptor
from magent.mcp.transport import McpCallOutcome, ProgressCallback

_COMPONENT = "mcp.stdio"


@dataclass(frozen=True)
class _SdkBundle:
    """Lazy SDK accessor bundle (kept as ``Any``: versions differ inside v1)."""

    module: Any
    ClientSession: Any
    StdioServerParameters: Any
    get_default_environment: Any
    stdio_client: Any


def _load_sdk() -> _SdkBundle:
    """Import the official SDK on first use; core stays importable without it."""
    try:
        import mcp  # type: ignore[import-not-found]
        from mcp import ClientSession, StdioServerParameters  # type: ignore[import-not-found]
        from mcp.client.stdio import (  # type: ignore[import-not-found]
            get_default_environment,
            stdio_client,
        )
    except ImportError as exc:
        raise McpInvalidConfigError(
            "the official MCP SDK is required for real transports; install it with "
            "`pip install magent[mcp]` (extras pin `mcp>=1.10,<2`)"
        ) from exc
    return _SdkBundle(
        module=mcp,
        ClientSession=ClientSession,
        StdioServerParameters=StdioServerParameters,
        get_default_environment=get_default_environment,
        stdio_client=stdio_client,
    )


def require_mcp_sdk() -> Any:
    """Return the official ``mcp`` module or raise an actionable error."""
    return _load_sdk().module


def _sdk_error_cls() -> type[BaseException] | None:
    try:
        from mcp.shared.exceptions import McpError  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - only when the extra is missing
        return None
    return McpError


def _read_result(result: Any) -> tuple[tuple[str, ...], dict[str, Any] | None]:
    """Extract ``(content_text, structured)`` from a ``CallToolResult``."""
    texts: list[str] = []
    for content in getattr(result, "content", ()) or ():
        ctype = getattr(content, "type", "")
        if ctype == "text":
            texts.append(str(getattr(content, "text", "")))
        else:
            # Bounded, credential-free representation of non-text blocks.
            texts.append(f"<{ctype or 'unknown'}>")
    structured = getattr(result, "structuredContent", None)
    if structured is not None and not isinstance(structured, dict):
        structured = None
    return tuple(texts), structured


def _progress_cb(on_progress: ProgressCallback | None) -> Callable[..., Any] | None:
    """Adapt the proxy's sync ``on_progress`` to the SDK async protocol."""
    if on_progress is None:
        return None

    async def _cb(progress: float, total: float | None, message: str | None) -> None:
        on_progress(
            {"progress": progress, "total": total, "message": message or ""}
        )

    return _cb


class StdioMcpTransport:
    """McpTransport over a local server process via the official SDK."""

    def __init__(
        self,
        *,
        command: str,
        args: Sequence[str] = (),
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        errlog: TextIO | None = None,
    ) -> None:
        if not command or not command.strip():
            raise McpInvalidConfigError("stdio command must not be empty")
        self._command = command
        self._args = tuple(args)
        self._env = dict(env) if env else None
        self._cwd = cwd
        self._errlog = errlog
        self._stack: AsyncExitStack | None = None
        self._session: Any = None
        self._server_info: dict[str, str] = {}

    # -- lifecycle --------------------------------------------------------------
    async def connect(self) -> None:
        """Spawn the server process and initialize the MCP session (idempotent)."""
        if self._session is not None:
            return
        sdk = _load_sdk()
        env: dict[str, str] = dict(sdk.get_default_environment())
        if self._env:
            env.update(self._env)
        params = sdk.StdioServerParameters(
            command=self._command,
            args=list(self._args),
            env=env,
            cwd=self._cwd,
        )
        stack = AsyncExitStack()
        try:
            if self._errlog is None:
                read_write = await stack.enter_async_context(sdk.stdio_client(params))
            else:
                read_write = await stack.enter_async_context(
                    sdk.stdio_client(params, errlog=self._errlog)
                )
            read, write = read_write
            session = await stack.enter_async_context(sdk.ClientSession(read, write))
            init = await session.initialize()
            info = getattr(init, "serverInfo", None)
            self._server_info = {
                "server_name": str(getattr(info, "name", "")),
                "server_version": str(getattr(info, "version", "")),
                "protocol_version": str(getattr(init, "protocolVersion", "")),
            }
            self._stack = stack
            self._session = session
        except BaseException:
            self._session = None
            self._stack = None
            try:
                await stack.aclose()
            except BaseException:  # noqa: BLE001 - teardown must not mask the cause
                pass
            raise

    def _require(self) -> Any:
        if self._session is None:
            raise McpPermanentError(_COMPONENT, "", "transport is not connected")
        return self._session

    # -- protocol surface --------------------------------------------------------
    async def list_tools(self) -> list[McpToolDescriptor]:
        session = self._require()
        result = await session.list_tools()
        descriptors: list[McpToolDescriptor] = []
        for tool in getattr(result, "tools", ()) or ():
            annotations = getattr(tool, "annotations", None)
            input_schema = getattr(tool, "inputSchema", None)
            output_schema = getattr(tool, "outputSchema", None)
            descriptors.append(
                McpToolDescriptor(
                    name=str(tool.name),
                    description=str(getattr(tool, "description", "") or ""),
                    input_schema=dict(input_schema) if input_schema else None,
                    output_schema=dict(output_schema) if output_schema else None,
                    read_only_hint=getattr(annotations, "readOnlyHint", None),
                    idempotent_hint=getattr(annotations, "idempotentHint", None),
                    destructive_hint=getattr(annotations, "destructiveHint", None),
                )
            )
        descriptors.sort(key=lambda d: d.name)
        return descriptors

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> McpCallOutcome:
        session = self._require()
        component = f"{_COMPONENT}:{tool_name}"
        try:
            result = await session.call_tool(
                tool_name,
                dict(arguments or {}),
                progress_callback=_progress_cb(on_progress),
            )
        except BaseException as exc:  # noqa: BLE001 - classified below, cancellation re-raised
            if isinstance(exc, asyncio.CancelledError):
                raise
            mapped = map_transport_exception(exc, component)
            raise mapped from exc
        texts, structured = _read_result(result)
        is_error = bool(getattr(result, "isError", False))
        return McpCallOutcome(
            content_text=texts,
            structured=structured,
            is_error=is_error,
            error_kind=None,
            error_message="\n".join(texts) if is_error else None,
            raw_meta=dict(self._server_info),
        )

    async def cancel_pending(self, tool_name: str) -> None:
        """Best-effort in-flight cancellation.

        The SDK cancels the in-flight request when the awaiting coroutine is
        cancelled (anyio scope, which the proxy's wall does). Protocol-level
        ``notifications/cancelled`` remains a future hook.
        """
        return None

    async def close(self) -> None:
        """Tear down the session and the server process; safe to call twice."""
        stack, self._stack = self._stack, None
        self._session = None
        if stack is not None:
            try:
                await stack.aclose()
            except BaseException:  # noqa: BLE001 - best-effort session teardown
                return

    # -- introspection -------------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._session is not None

    @property
    def server_info(self) -> dict[str, str]:
        return dict(self._server_info)


def stdio_transport(
    command: str,
    args: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    *,
    errlog: TextIO | None = None,
) -> StdioMcpTransport:
    """Build a real stdio transport (P10.2; requires the ``mcp`` extra)."""
    _load_sdk()  # actionable error early
    return StdioMcpTransport(
        command=command,
        args=args or (),
        env=env,
        cwd=cwd,
        errlog=errlog,
    )
