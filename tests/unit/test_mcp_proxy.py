"""Phase 10 — McpToolProxy behaviour and policy derivation.

Everything runs against the in-memory fake transport (no SDK, no network).
"""

from __future__ import annotations

import asyncio

import pytest

from magent.mcp.errors import (
    KIND_ELICITATION_DENIED,
    KIND_INVALID,
    KIND_PERMANENT,
    KIND_RATE_LIMITED,
    McpInvalidParamsError,
    McpPermanentError,
    McpRateLimitedError,
    McpTimeoutError,
    McpToolError,
    build_tool_error,
)
from magent.mcp.fake import (
    FakeMcpServer,
    FakeToolDefinition,
    InMemoryMcpTransport,
    fake_outcome,
)
from magent.mcp.proxy import (
    TOPIC_MCP_CALL_FINISHED,
    TOPIC_MCP_CALL_PROGRESS,
    TOPIC_MCP_CALL_STARTED,
    TOPIC_MCP_ELICITATION_DENIED,
    McpToolProxy,
    _derive_effect_policy,
)
from magent.mcp.schema import SCHEMA_MODE_ABSENT, SCHEMA_MODE_UNTYPED, build_input_model
from magent.mcp.spec import McpToolDescriptor
from magent.tools.context import ToolContext


def _recording_ctx(sink=None, cancel_event=None):
    events: list[tuple[str, dict]] = []

    def emit(topic, payload):
        events.append((topic, payload))
        return None

    ctx = ToolContext(
        run_id="r1",
        node_id="n1",
        side_effect_sink=sink,
        emit=emit,
        cancel_event=cancel_event,
    )
    return ctx, events


def _descriptor(
    name="echo",
    *,
    read_only=True,
    idempotent=None,
    schema=None,
    description="echo tool",
):
    return McpToolDescriptor(
        name=name,
        description=description,
        input_schema=schema,
        read_only_hint=read_only,
        idempotent_hint=idempotent,
    )


def _raising_handler(kind: str, message: str):
    def handler(args):
        raise build_tool_error(kind, "mcp:srv__x", "r1", message)

    return handler


async def _make_proxy(
    server: FakeMcpServer,
    descriptor: McpToolDescriptor,
    *,
    call_timeout: float | None = None,
    connect: bool = True,
):
    """Build a proxy for ``descriptor`` against ``server`` (connected by default)."""
    transport = InMemoryMcpTransport(server)
    if connect:
        await transport.connect()
    model, mode = build_input_model(descriptor.name, descriptor.input_schema)
    proxy = McpToolProxy(
        server_name="srv",
        descriptor=descriptor,
        transport=transport,
        input_model=model,
        schema_mode=mode,
        call_timeout=call_timeout,
    )
    return proxy


async def test_derive_effect_policy_matrix():
    assert _derive_effect_policy(_descriptor(read_only=True)) == (False, False)
    assert _derive_effect_policy(_descriptor(read_only=None, idempotent=True)) == (True, True)
    assert _derive_effect_policy(_descriptor(read_only=None, idempotent=None)) == (True, False)
    assert _derive_effect_policy(_descriptor(read_only=False, idempotent=True)) == (True, True)


async def test_construction_refuses_non_idempotent_side_effect():
    descriptor = _descriptor(read_only=None, idempotent=None)
    with pytest.raises(McpToolError) as info:
        await _make_proxy(FakeMcpServer("srv", []), descriptor, connect=False)
    assert "idempotent" in str(info.value)


async def test_spec_flags_follow_hints():
    server = FakeMcpServer(
        "srv",
        [FakeToolDefinition(name="probe", handler=lambda a: fake_outcome())],
    )
    proxy = await _make_proxy(
        server, _descriptor(name="probe", read_only=True, idempotent=True)
    )
    assert proxy.spec.side_effect is False
    assert proxy.spec.idempotent is False
    assert proxy.is_read_only is True

    server2 = FakeMcpServer(
        "srv",
        [FakeToolDefinition(name="notify", handler=lambda a: fake_outcome())],
    )
    proxy2 = await _make_proxy(
        server2,
        _descriptor(name="notify", read_only=None, idempotent=True),
    )
    assert proxy2.spec.side_effect is True
    assert proxy2.spec.idempotent is True
    assert proxy2.is_read_only is False


async def test_registered_name_is_qualified():
    server = FakeMcpServer(
        "srv", [FakeToolDefinition(name="echo", handler=lambda a: fake_outcome())]
    )
    proxy = await _make_proxy(server, _descriptor())
    assert proxy.registered_name == "srv__echo"
    assert proxy.spec.name == "srv__echo"


async def test_success_structured_outcome():
    server = FakeMcpServer(
        "srv",
        [
            FakeToolDefinition(
                name="echo",
                handler=lambda args: fake_outcome(
                    text=["hi"], structured={"echoed": args.get("msg")}
                ),
            )
        ],
    )
    proxy = await _make_proxy(server, _descriptor())
    ctx, events = _recording_ctx()
    res = await proxy.invoke({"msg": "hi"}, ctx)
    assert res.ok is True
    assert res.output == {"echoed": "hi"}
    assert res.structured == {"echoed": "hi"}
    assert res.meta["transport"] == "mcp"
    assert res.meta["registered_name"] == "srv__echo"
    topics = [topic for topic, _ in events]
    assert topics.count(TOPIC_MCP_CALL_STARTED) == 1
    assert topics.count(TOPIC_MCP_CALL_FINISHED) == 1
    finished = next(p for t, p in events if t == TOPIC_MCP_CALL_FINISHED)
    assert finished["ok"] is True
    assert server.call_log == [("echo", {"msg": "hi"})]


async def test_success_text_outcome():
    server = FakeMcpServer(
        "srv",
        [FakeToolDefinition(name="echo", handler=lambda args: fake_outcome(text=["a", "b"]))],
    )
    proxy = await _make_proxy(server, _descriptor())
    ctx, _ = _recording_ctx()
    res = await proxy.invoke({}, ctx)
    assert res.ok and res.output == "a\nb"


async def test_untyped_and_absent_modes_pass_raw_dicts():
    server = FakeMcpServer(
        "srv",
        [
            FakeToolDefinition(
                name="wild",
                input_schema={"type": "array"},
                read_only=True,
                handler=lambda args: fake_outcome(structured={"got": args}),
            ),
            FakeToolDefinition(
                name="bare",
                read_only=True,
                handler=lambda args: fake_outcome(structured={"got": args}),
            ),
        ],
    )
    wild, bare = await _make_proxy(
        server, _descriptor(name="wild", schema={"type": "array"})
    ), await _make_proxy(server, _descriptor(name="bare"))
    assert wild.schema_mode == SCHEMA_MODE_UNTYPED
    assert bare.schema_mode == SCHEMA_MODE_ABSENT
    ctx, _ = _recording_ctx()
    res_w = await wild.invoke({"anything": ["goes"]}, ctx)
    res_b = await bare.invoke({"anything": ["goes"]}, ctx)
    assert res_w.output["got"] == {"anything": ["goes"]}
    assert res_b.output["got"] == {"anything": ["goes"]}


async def test_tool_level_is_error_becomes_failure_result():
    server = FakeMcpServer(
        "srv",
        [
            FakeToolDefinition(
                name="echo",
                handler=lambda args: fake_outcome(
                    is_error=True,
                    error_kind=KIND_PERMANENT,
                    error_message="upstream down",
                ),
            )
        ],
    )
    proxy = await _make_proxy(server, _descriptor())
    ctx, events = _recording_ctx()
    res = await proxy.invoke({}, ctx)
    assert res.ok is False
    assert res.error["kind"] == KIND_PERMANENT
    assert res.error["retryable"] is False
    assert res.error["message"] == "upstream down"
    assert res.error["registered_name"] == "srv__echo"
    assert res.error["run_id"] == "r1"
    finished = [p for t, p in events if t == TOPIC_MCP_CALL_FINISHED]
    assert len(finished) == 1 and finished[0]["ok"] is False


async def test_elicitation_denied_emits_dedicated_event():
    server = FakeMcpServer(
        "srv",
        [FakeToolDefinition(name="ask", handler=lambda args: fake_outcome(), elicited=True)],
    )
    proxy = await _make_proxy(server, _descriptor(name="ask"))
    ctx, events = _recording_ctx()
    res = await proxy.invoke({}, ctx)
    assert res.ok is False
    assert res.error["kind"] == KIND_ELICITATION_DENIED
    deny = [t for t, _ in events if t == TOPIC_MCP_ELICITATION_DENIED]
    assert deny == [TOPIC_MCP_ELICITATION_DENIED]


async def test_raised_protocol_error_propagates_with_single_finished_event():
    server = FakeMcpServer(
        "srv",
        [
            FakeToolDefinition(
                name="bad",
                handler=_raising_handler(KIND_INVALID, "wrong params"),
            )
        ],
    )
    proxy = await _make_proxy(server, _descriptor(name="bad"))
    ctx, events = _recording_ctx()
    with pytest.raises(McpInvalidParamsError):
        await proxy.invoke({}, ctx)
    finished = [p for t, p in events if t == TOPIC_MCP_CALL_FINISHED]
    assert len(finished) == 1
    assert finished[0]["kind"] == KIND_INVALID


async def test_rate_limited_error_is_retriable_and_reachable():
    server = FakeMcpServer(
        "srv",
        [
            FakeToolDefinition(
                name="busy",
                handler=_raising_handler(KIND_RATE_LIMITED, "429 slow down"),
            )
        ],
    )
    proxy = await _make_proxy(server, _descriptor(name="busy"))
    ctx, _ = _recording_ctx()
    with pytest.raises(McpRateLimitedError):
        await proxy.invoke({}, ctx)


async def test_unknown_transport_exception_normalizes():
    def boom(args):
        raise ValueError("unwrap me")

    server = FakeMcpServer("srv", [FakeToolDefinition(name="buggy", handler=boom)])
    proxy = await _make_proxy(server, _descriptor(name="buggy"))
    ctx, events = _recording_ctx()
    with pytest.raises(McpToolError) as info:
        await proxy.invoke({}, ctx)
    err = info.value
    assert err.retryable is False
    assert err.cause is not None
    assert "unwrap me" in str(err)
    finished = [p for t, p in events if t == TOPIC_MCP_CALL_FINISHED]
    assert len(finished) == 1


async def test_timeout_is_the_hard_wall():
    async def sleepy(args):
        await asyncio.sleep(0.5)
        return fake_outcome(text="never")

    server = FakeMcpServer("srv", [FakeToolDefinition(name="slow", handler=sleepy)])
    proxy = await _make_proxy(server, _descriptor(name="slow"), call_timeout=0.05)
    ctx, events = _recording_ctx()
    with pytest.raises(McpTimeoutError):
        await proxy.invoke({}, ctx)
    finished = [p for t, p in events if t == TOPIC_MCP_CALL_FINISHED]
    assert finished[0]["kind"] == "timeout"


async def test_cancel_before_call_never_reaches_transport():
    server = FakeMcpServer(
        "srv", [FakeToolDefinition(name="echo", handler=lambda args: fake_outcome(text="x"))]
    )
    proxy = await _make_proxy(server, _descriptor())
    event = asyncio.Event()
    event.set()
    ctx, events = _recording_ctx(cancel_event=event)
    with pytest.raises(asyncio.CancelledError):
        await proxy.invoke({}, ctx)
    finished = [p for t, p in events if t == TOPIC_MCP_CALL_FINISHED]
    assert finished[0]["kind"] == "cancelled"
    assert server.call_log == []


async def test_async_emitter_awaitables_resolve():
    events: list[tuple[str, dict]] = []

    async def async_emit(topic, payload):
        events.append((topic, payload))
        await asyncio.sleep(0)

    server = FakeMcpServer(
        "srv", [FakeToolDefinition(name="echo", handler=lambda args: fake_outcome(text="ok"))]
    )
    proxy = await _make_proxy(server, _descriptor())
    ctx = ToolContext(run_id="r1", node_id="n1", emit=async_emit)
    res = await proxy.invoke({}, ctx)
    assert res.ok is True
    topics = [t for t, _ in events]
    assert topics.count(TOPIC_MCP_CALL_STARTED) == 1
    assert topics.count(TOPIC_MCP_CALL_FINISHED) == 1


async def test_emitter_failures_never_break_invocation():
    def bad_emit(topic, payload):
        raise RuntimeError("observability is dead")

    server = FakeMcpServer(
        "srv", [FakeToolDefinition(name="echo", handler=lambda args: fake_outcome(text="ok"))]
    )
    proxy = await _make_proxy(server, _descriptor())
    ctx = ToolContext(run_id="r1", node_id="n1", emit=bad_emit)
    res = await proxy.invoke({}, ctx)
    assert res.ok is True and res.output == "ok"


async def test_unconnected_transport_fails():
    server = FakeMcpServer(
        "srv", [FakeToolDefinition(name="echo", handler=lambda args: fake_outcome())]
    )
    proxy = await _make_proxy(server, _descriptor(), connect=False)
    ctx, events = _recording_ctx()
    with pytest.raises(McpPermanentError):
        await proxy.invoke({}, ctx)
    finished = [p for t, p in events if t == TOPIC_MCP_CALL_FINISHED]
    assert len(finished) == 1
