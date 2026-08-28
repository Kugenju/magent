"""Composable invocation middleware (phase 6).

Middleware wraps an agent/tool/LLM *call* — never the executor's scheduling,
retry or checkpoint logic. ``before`` runs in registration order, ``after`` in
reverse, and an exception propagates unchanged unless a middleware explicitly
converts it in ``on_error``. Middleware must not silently mutate framework
state; observability-only mutations go through ``inv.meta``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from pydantic import BaseModel

from magent.core.agent import BaseAgent


@dataclass
class Invocation:
    agent_name: str
    state: Any
    runtime: Any
    started_at: float
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Middleware(Protocol):
    async def before(self, inv: Invocation) -> None: ...
    async def after(self, inv: Invocation, response: Any) -> None: ...
    async def on_error(self, inv: Invocation, error: BaseException) -> None: ...


async def compose(
    inner: Callable[[Any, Any], Any],
    middlewares: list[Middleware],
) -> Callable[[Any, Any], Any]:
    """Return ``async def run(state, runtime)`` with ``middlewares`` applied.

    ``before`` runs in order, ``after`` in reverse; an exception is re-raised
    unchanged unless a middleware converts it in ``on_error``.
    """
    mws = list(middlewares)

    async def run(state: Any, runtime: Any) -> Any:
        inv = Invocation(
            agent_name=getattr(inner, "__name__", "agent"),
            state=state,
            runtime=runtime,
            started_at=time.time(),
        )
        for mw in mws:
            await mw.before(inv)
        try:
            response = await inner(state, runtime)
        except Exception as exc:
            converted: BaseException | None = None
            for mw in reversed(mws):
                try:
                    await mw.on_error(inv, exc)
                except Exception as conv:  # noqa: BLE001 - middleware converts
                    converted = conv
                    break
            if converted is not None:
                raise converted
            raise
        else:
            for mw in reversed(mws):
                await mw.after(inv, response)
            return response

    return run


class MiddlewareAgent(BaseAgent):
    """Wraps an inner agent so a middleware chain applies to its ``run``.

    The executor is unchanged: it just calls ``agent.run``, which is the
    composed (middleware-wrapped) call. This keeps retry/timeout/cancellation
    owned solely by the executor's ``run_node``.
    """

    def __init__(self, inner: BaseAgent, middlewares: list[Middleware], name: str | None = None) -> None:
        super().__init__(name or inner.name)
        self._inner = inner
        self._middlewares = list(middlewares)

    async def run(self, state: BaseModel, runtime) -> Any:
        async def _inner(s, r):
            return await self._inner.run(s, r)

        wrapped = await compose(_inner, self._middlewares)
        return await wrapped(state, runtime)


class LoggingMiddleware:
    def __init__(self, redact_fields: set[str] | None = None, logger=None) -> None:
        self._redact = redact_fields or set()
        self._log = logger

    async def before(self, inv: Invocation) -> None:
        self._say(inv, "before", self._redact_state(inv.state))

    async def after(self, inv: Invocation, response: Any) -> None:
        self._say(inv, "after", _redact_dict(getattr(response, "model_dump", lambda: {})(), self._redact))

    async def on_error(self, inv: Invocation, error: BaseException) -> None:
        self._say(inv, "error", {"error": type(error).__name__})

    def _redact_state(self, state: Any) -> dict:
        dump = state.model_dump() if isinstance(state, BaseModel) else {}
        return _redact_dict(dump, self._redact)

    def _say(self, inv: Invocation, stage: str, payload: Any) -> None:
        if self._log is not None:
            self._log.info("[mw:%s] %s %s", stage, inv.agent_name, payload)


class RateLimitMiddleware:
    """Caps concurrent invocations of the wrapped call via an asyncio semaphore."""

    def __init__(self, max_concurrent: int) -> None:
        import asyncio

        self._sem = asyncio.Semaphore(max_concurrent)

    async def before(self, inv: Invocation) -> None:
        await self._sem.acquire()
        inv.meta["rate_limited"] = True

    async def after(self, inv: Invocation, response: Any) -> None:
        self._sem.release()

    async def on_error(self, inv: Invocation, error: BaseException) -> None:
        self._sem.release()


class SizeLimitMiddleware:
    """Rejects inputs/outputs above a byte threshold (observability guard)."""

    def __init__(self, max_input_bytes: int | None = None, max_output_bytes: int | None = None) -> None:
        self._in = max_input_bytes
        self._out = max_output_bytes

    async def before(self, inv: Invocation) -> None:
        if self._in is not None:
            size = len(_canonical(inv.state))
            if size > self._in:
                from magent.tools.models import ToolValidationError

                raise ToolValidationError(f"input size {size} exceeds {self._in}")

    async def after(self, inv: Invocation, response: Any) -> None:
        if self._out is not None and response is not None:
            size = len(_canonical(response))
            if size > self._out:
                from magent.tools.models import ToolValidationError

                raise ToolValidationError(f"output size {size} exceeds {self._out}")

    async def on_error(self, inv: Invocation, error: BaseException) -> None:
        return None


class RedactionMiddleware:
    """Redacts sensitive fields from ``inv.meta`` only — never the real state."""

    def __init__(self, redact_fields: set[str]) -> None:
        self._redact = redact_fields

    async def before(self, inv: Invocation) -> None:
        inv.meta["redacted_input"] = _redact_dict(
            inv.state.model_dump() if isinstance(inv.state, BaseModel) else {}, self._redact
        )

    async def after(self, inv: Invocation, response: Any) -> None:
        return None

    async def on_error(self, inv: Invocation, error: BaseException) -> None:
        return None


def _canonical(obj: Any) -> str:
    from magent.checkpoint.models import canonical_json

    return canonical_json(obj.model_dump() if isinstance(obj, BaseModel) else obj)


def _redact_dict(obj: Any, fields: set[str]) -> Any:
    from magent.tools.registry import redact

    return redact(obj, fields)
