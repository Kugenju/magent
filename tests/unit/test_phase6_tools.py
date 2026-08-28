"""Phase 6 — tools layer tests."""

from __future__ import annotations

import asyncio
import time

import pytest
from pydantic import BaseModel

from magent.checkpoint.models import canonical_json
from magent.tools.context import ToolContext
from magent.tools.models import (
    ToolError,
    ToolPermissionError,
    ToolResult,
    ToolSpec,
    ToolTimeoutError,
    ToolValidationError,
)
from magent.tools.registry import (
    ConcurrencyLimiter,
    FunctionTool,
    ToolRegistry,
    redact,
    tool,
)


class AddIn(BaseModel):
    a: int
    b: int


class AddOut(BaseModel):
    sum: int


def _make_ctx(sink=None):
    return ToolContext(run_id="r1", node_id="n1", side_effect_sink=sink)


async def test_sync_function_tool_returns_result():
    t = FunctionTool("add", lambda args, ctx: AddOut(sum=args.a + args.b), output_model=AddOut)
    res = await t.invoke(AddIn(a=1, b=2), _make_ctx())
    assert res.ok and res.output.sum == 3


async def test_async_function_tool():
    async def run(args, ctx):
        return args.a * args.b

    t = FunctionTool("mul", run)
    res = await t.invoke(AddIn(a=2, b=3), _make_ctx())
    assert res.output == 6


def test_tool_decorator_sets_name_and_spec():
    @tool("hi", input_model=AddIn, output_model=AddOut)
    def hi(args, ctx):
        return AddOut(sum=args.a)

    assert isinstance(hi, FunctionTool)
    assert hi.spec.name == "hi"
    assert hi.spec.input_model is AddIn


async def test_input_validation_failure():
    reg = ToolRegistry()
    reg.register(FunctionTool("add", lambda a, c: None, input_model=AddIn))
    with pytest.raises(ToolValidationError):
        await reg.invoke("add", {"a": "x"}, _make_ctx())


async def test_output_validation_failure():
    t = FunctionTool("bad", lambda a, c: {"nope": 1}, output_model=AddOut)
    with pytest.raises(ToolValidationError):
        await t.invoke(AddIn(a=1, b=2), _make_ctx())


async def test_timeout_raises_tool_timeout():
    def slow(args, ctx):
        time.sleep(0.2)
        return "done"

    t = FunctionTool("slow", slow, timeout=0.01)
    with pytest.raises(ToolTimeoutError):
        await t.invoke(None, _make_ctx())


async def test_not_registered_denied():
    reg = ToolRegistry()
    with pytest.raises(ToolPermissionError):
        await reg.invoke("missing", {}, _make_ctx())


async def test_allowlist_denies_unlisted():
    reg = ToolRegistry(allowlist=["ok"])
    reg.register(FunctionTool("ok", lambda a, c: 1))
    reg.register(FunctionTool("bad", lambda a, c: 2))
    assert (await reg.invoke("ok", {}, _make_ctx())).ok
    with pytest.raises(ToolPermissionError):
        await reg.invoke("bad", {}, _make_ctx())


async def test_duplicate_registration_denied():
    reg = ToolRegistry()
    reg.register(FunctionTool("x", lambda a, c: 1))
    with pytest.raises(ToolPermissionError):
        reg.register(FunctionTool("x", lambda a, c: 2))


async def test_side_effect_requires_idempotent():
    reg = ToolRegistry()
    reg.register(FunctionTool("send", lambda a, c: "sent", side_effect=True, idempotent=False))
    with pytest.raises(ToolPermissionError):
        await reg.invoke("send", {}, _make_ctx())


class _FakeSink:
    def __init__(self):
        self.effects = {}
        self.calls = 0

    async def write(self, input_state, name, payload, effect_fn):
        key = (name, canonical_json(payload))
        if key in self.effects:
            return self.effects[key]
        self.calls += 1
        res = await effect_fn(payload)
        self.effects[key] = res
        return res


async def test_side_effect_idempotent_funnel_runs_once():
    sink = _FakeSink()
    reg = ToolRegistry()
    reg.register(FunctionTool("pub", lambda a, c: "v", side_effect=True, idempotent=True))
    ctx = _make_ctx(sink=sink)
    r1 = await reg.invoke("pub", {"k": 1}, ctx)
    r2 = await reg.invoke("pub", {"k": 1}, ctx)
    assert r1.ok and r2.ok
    assert sink.calls == 1


async def test_concurrency_limiter_caps():
    limiter = ConcurrencyLimiter(2)
    reg = ToolRegistry(limiter=limiter)
    reg.register(FunctionTool("t", lambda a, c: 1))
    running = 0
    peak = 0

    def work(args, ctx):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        time.sleep(0.05)
        running -= 1
        return 1

    reg._tools["t"] = FunctionTool("t", work)
    await asyncio.gather(*[reg.invoke("t", {}, _make_ctx()) for _ in range(6)])
    assert peak <= 2


async def test_input_size_limit():
    reg = ToolRegistry(max_input_bytes=5)
    reg.register(FunctionTool("t", lambda a, c: 1))
    with pytest.raises(ToolValidationError):
        await reg.invoke("t", {"payload": "x" * 100}, _make_ctx())


def test_redact_helper():
    out = redact({"a": 1, "secret": "x", "nested": {"secret": "y"}}, {"secret"})
    assert out == {"a": 1, "secret": "***", "nested": {"secret": "***"}}


def test_tool_result_helpers():
    assert ToolResult.success(output=1).ok
    assert not ToolResult.failure({"why": "boom"}).ok


def test_tool_spec_metadata():
    spec = ToolSpec("s", version="2", side_effect=True, idempotent=True)
    m = spec.to_metadata()
    assert m["name"] == "s" and m["side_effect"] and m["idempotent"]


async def test_context_cancellation_detected():
    class Ev:
        def __init__(self):
            self._set = False

        def is_set(self):
            return self._set

    ev = Ev()
    ctx = ToolContext(run_id="r", node_id="n", cancel_event=ev)
    assert not ctx.is_cancelled()
    ev._set = True
    assert ctx.is_cancelled()


async def test_tool_error_normalized():
    def boom(args, ctx):
        raise ValueError("nope")

    t = FunctionTool("boom", boom)
    with pytest.raises(ToolError):
        await t.invoke(AddIn(a=1, b=1), _make_ctx())
