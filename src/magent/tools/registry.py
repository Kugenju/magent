"""Tool registry, function adapter and policy enforcement (phase 6).

The registry is the single place where tool *policy* is enforced: registration
uniqueness, the allowlist, input/output schema validation, size limits, a
concurrency limiter, timeouts and redaction. Side-effect tools are funnelled
through a :class:`SideEffectSink` so a repeated execution key is only executed
once.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from pydantic import BaseModel

from magent.checkpoint.idempotency import SideEffectSink
from magent.checkpoint.models import canonical_json

from .context import ToolContext
from .models import (
    ToolError,
    ToolPermissionError,
    ToolResult,
    ToolSpec,
    ToolTimeoutError,
    ToolValidationError,
)


class FunctionTool:
    """Adapts a plain sync/async ``func(args, ctx)`` into the :class:`Tool` shape."""

    def __init__(
        self,
        name: str,
        func: Callable,
        *,
        version: str = "1",
        description: str = "",
        input_model: type[BaseModel] | None = None,
        output_model: type[BaseModel] | None = None,
        side_effect: bool = False,
        idempotent: bool = False,
        timeout: float | None = None,
    ) -> None:
        self.spec = ToolSpec(
            name,
            version=version,
            description=description,
            input_model=input_model,
            output_model=output_model,
            side_effect=side_effect,
            idempotent=idempotent,
        )
        self._func = func
        self._input = input_model
        self._output = output_model
        self._timeout = timeout

    async def invoke(self, arguments: BaseModel, context: ToolContext) -> ToolResult:
        try:
            if asyncio.iscoroutinefunction(self._func):
                coro: Any = self._func(arguments, context)
            else:
                coro = asyncio.to_thread(self._func, arguments, context)
            if self._timeout is not None:
                result = await asyncio.wait_for(coro, self._timeout)
            else:
                result = await coro
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            raise ToolTimeoutError(
                f"tool {self.spec.name!r} timed out after {self._timeout}s"
            )
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize to ToolError
            raise ToolError(self.spec.name, context.run_id, str(exc), cause=exc)

        if self._output is not None and not isinstance(result, self._output):
            try:
                result = self._output.model_validate(result)
            except Exception as exc:
                raise ToolValidationError(
                    f"tool {self.spec.name!r} output failed validation: {exc}"
                )
        return ToolResult.success(output=result)


def tool(
    name: str | None = None,
    *,
    version: str = "1",
    description: str = "",
    input_model: type[BaseModel] | None = None,
    output_model: type[BaseModel] | None = None,
    side_effect: bool = False,
    idempotent: bool = False,
    timeout: float | None = None,
) -> Callable[[Callable], FunctionTool]:
    """Decorator turning a sync/async function into a :class:`FunctionTool`."""

    def deco(func: Callable) -> FunctionTool:
        return FunctionTool(
            name or func.__name__,
            func,
            version=version,
            description=description or (func.__doc__ or "").strip(),
            input_model=input_model,
            output_model=output_model,
            side_effect=side_effect,
            idempotent=idempotent,
            timeout=timeout,
        )

    return deco


class ConcurrencyLimiter:
    """Bounded semaphore used to cap concurrent tool invocations."""

    def __init__(self, max_concurrent: int) -> None:
        self._sem = asyncio.Semaphore(max_concurrent)

    async def acquire(self) -> None:
        await self._sem.acquire()

    def release(self) -> None:
        self._sem.release()


def redact(obj: Any, fields: set[str]) -> Any:
    """Return a copy of ``obj`` with ``fields`` replaced by ``"***"``."""
    if isinstance(obj, dict):
        return {k: ("***" if k in fields else redact(v, fields)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v, fields) for v in obj]
    return obj


class ToolRegistry:
    """Holds registered tools and enforces every invocation policy."""

    def __init__(
        self,
        *,
        allowlist: list[str] | None = None,
        max_input_bytes: int | None = None,
        max_output_bytes: int | None = None,
        limiter: ConcurrencyLimiter | None = None,
        redact_fields: set[str] | None = None,
    ) -> None:
        self._tools: dict[str, FunctionTool] = {}
        self._allowlist = set(allowlist) if allowlist is not None else None
        self._max_input_bytes = max_input_bytes
        self._max_output_bytes = max_output_bytes
        self._limiter = limiter
        self._redact_fields = redact_fields or set()

    # -- registration -----------------------------------------------------
    def register(self, t: FunctionTool) -> None:
        if t.spec.name in self._tools:
            raise ToolPermissionError(
                f"tool {t.spec.name!r} is already registered (duplicate registration)"
            )
        self._tools[t.spec.name] = t

    def get(self, name: str) -> FunctionTool:
        t = self._tools.get(name)
        if t is None:
            raise ToolPermissionError(f"tool {name!r} is not registered")
        return t

    def is_allowed(self, name: str) -> bool:
        if self._allowlist is None:
            return name in self._tools
        return name in self._allowlist

    # -- invocation -------------------------------------------------------
    async def invoke(
        self, name: str, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolPermissionError(f"tool {name!r} is not registered")
        if not self.is_allowed(name):
            raise ToolPermissionError(f"tool {name!r} is not on the allowlist")

        spec = tool.spec
        if spec.input_model is not None:
            try:
                args = spec.input_model.model_validate(arguments)
            except Exception as exc:
                raise ToolValidationError(
                    f"tool {name!r} input failed validation: {exc}"
                )
        else:
            args = arguments  # type: ignore[assignment]

        if self._max_input_bytes is not None and len(canonical_json(arguments)) > self._max_input_bytes:
            raise ToolValidationError(f"tool {name!r} input exceeds size limit")

        if self._limiter is not None:
            await self._limiter.acquire()
        try:
            if spec.side_effect and not spec.idempotent:
                raise ToolPermissionError(
                    f"side-effect tool {name!r} requires idempotent=True"
                )

            if spec.side_effect and context.side_effect_sink is not None:
                result_dict = await context.side_effect_sink.write(
                    dict(arguments),
                    name,
                    dict(arguments),
                    self._make_effect(tool, args, context),
                )
                return ToolResult.model_validate(result_dict)

            result = await tool.invoke(args, context)
            if (
                self._max_output_bytes is not None
                and result.output is not None
                and len(canonical_json(result.output)) > self._max_output_bytes
            ):
                raise ToolValidationError(f"tool {name!r} output exceeds size limit")
            return result
        finally:
            if self._limiter is not None:
                self._limiter.release()

    @staticmethod
    def _make_effect(tool: FunctionTool, args: Any, context: ToolContext):
        async def _effect(_payload) -> dict:
            res = await tool.invoke(args, context)
            return res.model_dump()

        return _effect
