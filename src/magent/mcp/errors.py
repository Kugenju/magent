"""MCP error taxonomy and classification mapping (phase 10).

MCP failures are normalized into the magent ``ToolError`` family so the existing
reliability machinery can consume them unchanged:

- Retryable kinds (rate limited / timeout / transient) are *also* instances of
  ``RetryableError``, therefore ``classify_exception`` (reliability runner)
  treats a raised error as retryable under the configured ``RetryPolicy``.
- Non-retryable kinds (auth / forbidden / invalid / permanent / elicitation
  denied) stay plain ``ToolError`` subclasses: fail-fast, never retried.

Every error carries a ``kind`` token suitable for attempt events and traces.
Messages never include credentials or raw payloads.
"""

from __future__ import annotations

import asyncio

from magent.core.errors import MagentError
from magent.reliability.errors import RetryableError
from magent.tools.models import ToolError, ToolTimeoutError

_CLIP_LIMIT = 2000


def _clip_message(text: str) -> str:
    text = text or ""
    return text if len(text) <= _CLIP_LIMIT else text[: _CLIP_LIMIT - 3] + "..."

# Error kinds (stable tokens, safe for traces/events).
KIND_RATE_LIMITED = "rate_limited"
KIND_TIMEOUT = "timeout"
KIND_TRANSIENT = "transient"
KIND_AUTH = "auth"
KIND_FORBIDDEN = "forbidden"
KIND_INVALID = "invalid"
KIND_PERMANENT = "permanent"
KIND_ELICITATION_DENIED = "elicitation_denied"

RETRYABLE_KINDS = (
    KIND_RATE_LIMITED,
    KIND_TIMEOUT,
    KIND_TRANSIENT,
)

NON_RETRYABLE_KINDS = (
    KIND_AUTH,
    KIND_FORBIDDEN,
    KIND_INVALID,
    KIND_PERMANENT,
    KIND_ELICITATION_DENIED,
)


class McpToolError(ToolError):
    """Base class for normalized MCP failures.

    ``kind`` is a stable token from the ``KIND_*`` constants; ``retryable``
    mirrors the reliability classifier so agents and tests can branch on it
    without importing reliability internals.
    """

    kind: str = "mcp_error"
    retryable: bool = False

    def __init__(
        self,
        component: str,
        run_id: str,
        message: str,
        *,
        kind: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(component, run_id, message, cause=cause)
        if kind is not None:
            self.kind = kind


class McpRateLimitedError(McpToolError, RetryableError):
    """Server rate limit (429-like). Retryable under RetryPolicy."""

    kind = KIND_RATE_LIMITED
    retryable = True


class McpTimeoutError(McpToolError, ToolTimeoutError, RetryableError):
    """Per-call timeout exceeded. Retryable; also matches ToolTimeoutError."""

    kind = KIND_TIMEOUT
    retryable = True


class McpTransientError(McpToolError, RetryableError):
    """Transient transport/network failure. Retryable under RetryPolicy."""

    kind = KIND_TRANSIENT
    retryable = True


class McpAuthError(McpToolError):
    """Authentication/authorization failure. Never retried."""

    kind = KIND_AUTH
    retryable = False


class McpForbiddenError(McpToolError):
    """Access denied by policy or server. Never retried."""

    kind = KIND_FORBIDDEN
    retryable = False


class McpInvalidParamsError(McpToolError):
    """Server rejected the call (bad arguments / unknown tool). Never retried."""

    kind = KIND_INVALID
    retryable = False


class McpPermanentError(McpToolError):
    """Server-side tool failure or unrecoverable condition. Never retried."""

    kind = KIND_PERMANENT
    retryable = False


class McpElicitationDeniedError(McpToolError):
    """Server requested interactive elicitation; the adapter denies by default.

    Phase 10 provides no human-in-the-loop channel: the request is rejected and
    surfaced as a non-retryable tool error plus an observability event.
    """

    kind = KIND_ELICITATION_DENIED
    retryable = False


class McpInvalidConfigError(MagentError):
    """Loader/server configuration violated the phase-10 contract (not a call failure)."""


_KIND_TO_CLASS: dict[str, type[McpToolError]] = {
    KIND_RATE_LIMITED: McpRateLimitedError,
    KIND_TIMEOUT: McpTimeoutError,
    KIND_TRANSIENT: McpTransientError,
    KIND_AUTH: McpAuthError,
    KIND_FORBIDDEN: McpForbiddenError,
    KIND_INVALID: McpInvalidParamsError,
    KIND_PERMANENT: McpPermanentError,
    KIND_ELICITATION_DENIED: McpElicitationDeniedError,
}


def error_class_for_kind(kind: str) -> type[McpToolError]:
    """Return the concrete error class for an error kind token.

    Unknown kinds map conservatively to the base ``McpToolError`` (non-retryable),
    matching the framework's "unknown failure = never retried" stance.
    """
    return _KIND_TO_CLASS.get(kind, McpToolError)


def build_tool_error(
    kind: str,
    component: str,
    run_id: str,
    message: str,
    *,
    cause: BaseException | None = None,
) -> McpToolError:
    """Build the classified error instance for ``kind`` with explicit context."""
    cls = error_class_for_kind(kind)
    return cls(component, run_id, message, kind=kind, cause=cause)


# JSON-RPC codes meaning "the caller must fix something" (never retried):
# -32700 parse / -32600 invalid request / -32601 method not found / -32602 params.
_CALLER_FAULT_CODES = (-32700, -32600, -32601, -32602)
# JSON-RPC -32603 (internal error) and the SDK's CONNECTION_CLOSED (-32000)
# are worth a retry under RetryPolicy when one is configured.
_TRANSIENT_CODES = (-32603, -32000)


def _kind_for_jsonrpc_code(code: int | None) -> str:
    """Map a JSON-RPC error code onto an ``magent.mcp`` error kind."""
    if code is None:
        return KIND_PERMANENT
    if code in _CALLER_FAULT_CODES:
        return KIND_INVALID
    if code in _TRANSIENT_CODES:
        return KIND_TRANSIENT
    return KIND_PERMANENT


def map_transport_exception(
    exc: BaseException,
    component: str,
    run_id: str = "",
) -> McpToolError:
    """Normalize an SDK/transport exception into the classified error family.

    ``CancelledError`` must never be passed here - callers re-raise cancellation
    unchanged. ``TimeoutError`` maps to the retryable ``timeout`` kind; SDK
    protocol errors map through the JSON-RPC table; connection-style failures
    map to ``transient``; anything unknown maps conservatively to ``permanent``
    (framework stance: unknown failure = never retried).
    """
    if isinstance(exc, McpToolError):
        return exc
    if isinstance(exc, asyncio.TimeoutError):
        return build_tool_error(
            KIND_TIMEOUT,
            component,
            run_id,
            _clip_message(f"{type(exc).__name__}: {exc}"),
            cause=exc,
        )
    message = f"{type(exc).__name__}: {exc}"
    try:
        from mcp.shared.exceptions import McpError  # type: ignore[import-not-found]

        sdk_error_cls: type[BaseException] | None = McpError
    except ImportError:  # pragma: no cover - only when the extra is missing
        sdk_error_cls = None
    if sdk_error_cls is not None and isinstance(exc, sdk_error_cls):
        error = getattr(exc, "error", None)
        code = getattr(error, "code", None)
        text = getattr(error, "message", None) or message
        return build_tool_error(
            _kind_for_jsonrpc_code(code),
            component,
            run_id,
            _clip_message(text),
            cause=exc,
        )
    if isinstance(exc, (ConnectionError, BrokenPipeError, EOFError)):
        return build_tool_error(
            KIND_TRANSIENT, component, run_id, _clip_message(message), cause=exc
        )
    if isinstance(exc, OSError):
        return build_tool_error(
            KIND_TRANSIENT, component, run_id, _clip_message(message), cause=exc
        )
    return build_tool_error(
        KIND_PERMANENT, component, run_id, _clip_message(message), cause=exc
    )
