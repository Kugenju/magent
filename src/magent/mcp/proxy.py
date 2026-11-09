"""MCP tool -> framework tool adapter (phase 10, P10.1).

``McpToolProxy`` subclasses :class:`FunctionTool` so the entire phase-6 policy
pipeline (allowlist, input/output validation, size limit, concurrency limiter,
``SideEffectSink`` idempotency funnel) applies to MCP tools exactly as to local
tools. The proxy owns only the transport-level translation layer:

- arguments: pydantic model or raw dict -> plain dict for ``tools/call``;
- outcomes: a server-side tool failure (``isError=True``) becomes
  ``ToolResult.failure`` with a machine-readable ``error`` dict carrying
  ``kind``/``retryable``; transport/protocol failures raise classified
  :class:`McpToolError` subclasses;
- the per-call timeout is the magent-side hard wall (MCP background tasks are
  intentionally not consumed in phase 10 - they never extend it);
- lifecycle events flow through ``ToolContext.emit`` into the EventBus as an
  observability side channel (never into state).
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from magent.tools.context import ToolContext
from magent.tools.models import ToolResult
from magent.tools.registry import FunctionTool

from .errors import (
    McpElicitationDeniedError,
    McpToolError,
    McpTimeoutError,
    error_class_for_kind,
)
from .schema import dump_arguments
from .spec import McpToolDescriptor, validate_component
from .transport import McpTransport, ProgressCallback

TOPIC_MCP_CALL_STARTED = "tool.mcp.call.started"
TOPIC_MCP_CALL_FINISHED = "tool.mcp.call.finished"
TOPIC_MCP_CALL_PROGRESS = "tool.mcp.progress"
TOPIC_MCP_ELICITATION_DENIED = "tool.mcp.elicitation_denied"

_MESSAGE_LIMIT = 2000     # bounded messages in errors/events
_DESCRIPTION_LIMIT = 500  # bounded tool descriptions

_KIND_TIMEOUT = "timeout"
_KIND_CANCELLED = "cancelled"


def _clip(text: str) -> str:
    text = text or ""
    return text if len(text) <= _MESSAGE_LIMIT else text[: _MESSAGE_LIMIT - 3] + "..."


def _derive_effect_policy(descriptor: McpToolDescriptor) -> tuple[bool, bool]:
    """Return ``(side_effect, idempotent)`` from server annotation hints.

    Strict-by-default: an absent ``read_only_hint`` is treated as "not proven
    read-only", therefore side-effecting, which then requires the explicit
    ``idempotent_hint=True`` guarantee (the loader rejects otherwise).
    """
    if descriptor.read_only_hint is True:
        return False, False
    idempotent = descriptor.idempotent_hint is True
    return True, idempotent


class McpToolProxy(FunctionTool):
    """Framework-facing view of one MCP server tool.

    Registered under the qualified name ``<server>__<tool>`` so server-level
    namespaces can never collide with local tools or with each other.
    """

    def __init__(
        self,
        *,
        server_name: str,
        descriptor: McpToolDescriptor,
        transport: McpTransport,
        input_model: type[BaseModel] | None,
        schema_mode: str,
        call_timeout: float | None,
    ) -> None:
        validate_component(server_name, "server")
        validate_component(descriptor.name, "tool")
        side_effect, idempotent = _derive_effect_policy(descriptor)
        if side_effect and not idempotent:
            raise McpToolError(
                "mcp.proxy",
                "",
                f"tool {descriptor.name!r} of server {server_name!r}: side-effecting "
                "(read-only hint absent/false) without idempotent hint - registration "
                "refused by the strict phase-10 policy",
            )
        registered_name = f"{server_name}__{descriptor.name}"
        description = (
            descriptor.description
            or f"MCP tool {descriptor.name!r} from server {server_name!r}"
        )[:_DESCRIPTION_LIMIT]
        self.server_name = server_name
        self.descriptor = descriptor
        self._mcp_transport = transport
        self.schema_mode = schema_mode
        self._call_timeout = call_timeout

        async def _unused_noop(args: Any, ctx: ToolContext) -> None:  # pragma: no cover
            raise RuntimeError("McpToolProxy.invoke is overridden; _func must not run")

        super().__init__(
            registered_name,
            _unused_noop,
            version="1",
            description=description,
            input_model=input_model,
            output_model=None,
            side_effect=side_effect,
            idempotent=idempotent,
            timeout=call_timeout,
        )

    # -- public surface ------------------------------------------------------
    @property
    def registered_name(self) -> str:
        return self.spec.name

    @property
    def is_read_only(self) -> bool:
        return self.descriptor.read_only_hint is True

    # -- observability helpers ------------------------------------------------
    def _event_payload(self, context: ToolContext, extra: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "server": self.server_name,
            "tool": self.descriptor.name,
            "registered_name": self.registered_name,
            "schema_mode": self.schema_mode,
            "run_id": context.run_id,
            "node_id": context.node_id,
        }
        payload.update(extra)
        return payload

    def _result_meta(self, context: ToolContext, duration_ms: float) -> dict[str, Any]:
        return {
            "transport": "mcp",
            "server": self.server_name,
            "tool": self.descriptor.name,
            "registered_name": self.registered_name,
            "schema_mode": self.schema_mode,
            "duration_ms": round(duration_ms, 3),
            "run_id": context.run_id,
            "node_id": context.node_id,
        }

    def _make_progress_cb(self, fire: Callable[[str, dict[str, Any]], None]) -> ProgressCallback:
        def _on_progress(payload: dict[str, Any]) -> None:
            safe = payload if isinstance(payload, dict) else {"raw": payload}
            fire(TOPIC_MCP_CALL_PROGRESS, safe)

        return _on_progress

    async def _best_effort_cancel(self) -> None:
        try:
            await self._mcp_transport.cancel_pending(self.descriptor.name)
        except Exception:  # noqa: BLE001 - cleanup must never mask the original outcome
            return

    # -- invocation ------------------------------------------------------------
    async def invoke(self, arguments: BaseModel, context: ToolContext) -> ToolResult:
        pending: list[Awaitable[None]] = []
        component = f"mcp:{self.registered_name}"
        finished_fired = False

        def fire(topic: str, payload: dict[str, Any]) -> None:
            try:
                emitted = context.emit(topic, payload)
            except Exception:  # noqa: BLE001 - observability must never break execution
                return
            if inspect.isawaitable(emitted):
                pending.append(emitted)

        def fire_finished(payload: dict[str, Any]) -> None:
            nonlocal finished_fired
            finished_fired = True
            fire(TOPIC_MCP_CALL_FINISHED, payload)

        async def flush() -> None:
            while pending:
                item = pending.pop(0)
                try:
                    if inspect.isawaitable(item):
                        await item
                except BaseException:  # noqa: BLE001 - cleanup is best-effort
                    continue

        fire(TOPIC_MCP_CALL_STARTED, self._event_payload(context, {}))
        started = time.monotonic()
        try:
            if context.is_cancelled():
                fire_finished(
                    self._event_payload(context, {"ok": False, "kind": _KIND_CANCELLED})
                )
                raise asyncio.CancelledError(
                    f"mcp tool {self.registered_name!r} cancelled before call"
                )
            try:
                raw_args = dump_arguments(arguments)
                coro = self._mcp_transport.call_tool(
                    self.descriptor.name, raw_args, on_progress=self._make_progress_cb(fire)
                )
                if self._call_timeout is not None:
                    outcome = await asyncio.wait_for(coro, self._call_timeout)
                else:
                    outcome = await coro
            except asyncio.TimeoutError:
                await self._best_effort_cancel()
                fire_finished(
                    self._event_payload(
                        context,
                        {"ok": False, "kind": _KIND_TIMEOUT, "timeout": self._call_timeout},
                    ),
                )
                raise McpTimeoutError(
                    component,
                    context.run_id,
                    f"mcp call {self.registered_name!r} timed out after "
                    f"{self._call_timeout}s",
                ) from None
            except asyncio.CancelledError:
                await self._best_effort_cancel()
                fire_finished(
                    self._event_payload(context, {"ok": False, "kind": _KIND_CANCELLED})
                )
                raise
        except McpToolError as exc:
            if isinstance(exc, McpElicitationDeniedError):
                fire(TOPIC_MCP_ELICITATION_DENIED, self._event_payload(context, {}))
            if not finished_fired:
                fire_finished(
                    self._event_payload(
                        context,
                        {"ok": False, "kind": exc.kind, "message": _clip(exc.message)},
                    ),
                )
            raise
        except Exception as exc:  # noqa: BLE001 - normalize unknown transport bugs
            wrapped = McpToolError(
                component,
                context.run_id,
                _clip(f"unknown transport failure: {type(exc).__name__}: {str(exc)}"),
                cause=exc,
            )
            if not finished_fired:
                fire_finished(
                    self._event_payload(context, {"ok": False, "kind": wrapped.kind})
                )
            raise wrapped from exc
        else:
            duration_ms = (time.monotonic() - started) * 1000.0
            if outcome.is_error:
                kind = outcome.error_kind or "permanent"
                cls = error_class_for_kind(kind)
                if kind == "elicitation_denied":
                    fire(TOPIC_MCP_ELICITATION_DENIED, self._event_payload(context, {}))
                fire_finished(
                    self._event_payload(
                        context,
                        {
                            "ok": False,
                            "kind": kind,
                            "duration_ms": round(duration_ms, 3),
                            "message": _clip(outcome.error_message or ""),
                        },
                    ),
                )
                return ToolResult.failure(
                    error={
                        "type": cls.__name__,
                        "kind": kind,
                        "message": _clip(outcome.error_message or "mcp tool reported failure"),
                        "retryable": cls.retryable,
                        "server": self.server_name,
                        "tool": self.descriptor.name,
                        "registered_name": self.registered_name,
                        "run_id": context.run_id,
                    },
                    meta=self._result_meta(context, duration_ms),
                )

            fire_finished(
                self._event_payload(
                    context,
                    {"ok": True, "kind": None, "duration_ms": round(duration_ms, 3)},
                ),
            )
            output = outcome.structured if outcome.structured is not None else outcome.text
            return ToolResult.success(
                output=output,
                structured=outcome.structured,
                meta=self._result_meta(context, duration_ms),
            )
        finally:
            await flush()
