"""Phase 6 — middleware tests."""

from __future__ import annotations

import asyncio
import time

import pytest

from pydantic import BaseModel

from magent.middleware import (
    LoggingMiddleware,
    MiddlewareAgent,
    RateLimitMiddleware,
    RedactionMiddleware,
    SizeLimitMiddleware,
    compose,
)
from magent.core.agent import BaseAgent
from magent.core.errors import MagentError


class S(BaseModel):
    value: int


async def test_compose_ordering():
    log = []

    async def inner(state, runtime):
        log.append("inner")
        return "ok"

    # convert Order middlewares into protocol objects
    class MW:
        def __init__(self, order):
            self.o = order

        async def before(self, inv):
            log.append(f"b:{self.o}")

        async def after(self, inv, resp):
            log.append(f"a:{self.o}")

        async def on_error(self, inv, err):
            return None

    run = await compose(inner, [MW("1"), MW("2")])
    await run(S(value=1), None)
    assert log == ["b:1", "b:2", "inner", "a:2", "a:1"]


async def test_on_error_converts():
    class Convert:
        async def before(self, inv):
            return None

        async def after(self, inv, resp):
            return None

        async def on_error(self, inv, err):
            raise MagentError("converted", "", "x")

    async def inner(state, runtime):
        raise ValueError("orig")

    run = await compose(inner, [Convert()])
    with pytest.raises(MagentError):
        await run(S(value=1), None)


async def test_on_error_default_reraises_original():
    class Noop:
        async def before(self, inv):
            return None

        async def after(self, inv, resp):
            return None

        async def on_error(self, inv, err):
            return None

    async def inner(state, runtime):
        raise KeyError("orig")

    run = await compose(inner, [Noop()])
    with pytest.raises(KeyError):
        await run(S(value=1), None)


async def test_logging_middleware_captures():
    captured = []

    class L:
        def info(self, fmt, *a):
            captured.append(fmt % a)

    mw = LoggingMiddleware(logger=L())

    async def inner(state, runtime):
        return "ok"

    run = await compose(inner, [mw])
    await run(S(value=1), None)
    assert any("before" in c for c in captured) and any("after" in c for c in captured)


async def test_rate_limit_middleware_caps():
    limiter = RateLimitMiddleware(2)
    peak = 0
    running = 0

    async def inner(state, runtime):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return "ok"

    run = await compose(inner, [limiter])
    await asyncio.gather(*[run(S(value=i), None) for i in range(6)])
    assert peak <= 2


async def test_size_limit_input():
    mw = SizeLimitMiddleware(max_input_bytes=5)

    async def inner(state, runtime):
        return "ok"

    run = await compose(inner, [mw])
    with pytest.raises(Exception):
        await run(S(value=123456), None)


async def test_size_limit_output():
    mw = SizeLimitMiddleware(max_output_bytes=5)

    class Big(BaseModel):
        data: str = "x" * 100

    async def inner(state, runtime):
        return Big()

    run = await compose(inner, [mw])
    with pytest.raises(Exception):
        await run(S(value=1), None)


async def test_redaction_middleware_only_meta():
    mw = RedactionMiddleware({"value"})
    seen = {}

    class Capture:
        async def before(self, inv):
            seen["before"] = inv.meta.get("redacted_input")

        async def after(self, inv, resp):
            return None

        async def on_error(self, inv, err):
            return None

    async def inner(state, runtime):
        return "ok"

    run = await compose(inner, [mw, Capture()])
    await run(S(value=42), None)
    assert seen["before"] == {"value": "***"}


class _Inner(BaseAgent):
    def __init__(self):
        super().__init__("inner")

    async def run(self, state, runtime):
        return f"ran:{state.value}"


async def test_middleware_agent_wraps():
    log = []

    class Track:
        async def before(self, inv):
            log.append("before")

        async def after(self, inv, resp):
            log.append("after")

        async def on_error(self, inv, err):
            return None

    agent = MiddlewareAgent(_Inner(), [Track()])
    result = await agent.run(S(value=7), None)
    assert result == "ran:7"
    assert log == ["before", "after"]


async def test_middleware_agent_preserves_run_semantics():
    agent = MiddlewareAgent(_Inner(), [])
    assert agent.name == "inner"
