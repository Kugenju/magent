"""Phase 10 — MCP toolset loader: policy gates, registration, snapshot."""

from __future__ import annotations

import pytest

from magent.checkpoint import InMemoryCheckpointStore, SideEffectSink
from magent.mcp.errors import (
    KIND_ELICITATION_DENIED,
    McpInvalidConfigError,
    McpToolError,
)
from magent.mcp.fake import (
    FakeMcpServer,
    FakeToolDefinition,
    FakeTransportFactory,
    fake_outcome,
)
from magent.mcp.loader import McpToolLoader
from magent.mcp.spec import McpServerConfig
from magent.tools.context import ToolContext
from magent.tools.models import (
    ToolPermissionError,
    ToolValidationError,
)
from magent.tools.registry import FunctionTool, ToolRegistry

DRY = "r1"


def _echo_args_schema():
    return {
        "type": "object",
        "properties": {"msg": {"type": "string"}},
        "required": ["msg"],
    }


def _builder_server_tools():
    echo = FakeToolDefinition(
        name="echo",
        description="echo tool",
        input_schema=_echo_args_schema(),
        read_only=True,
        handler=lambda args: fake_outcome(text=f"echo:{args.get('msg', '')}"),
    )
    untyped = FakeToolDefinition(
        name="wild",
        input_schema={"type": "array"},
        read_only=True,
        handler=lambda args: fake_outcome(structured={"got": args}),
    )
    absent = FakeToolDefinition(
        name="bare",
        read_only=True,
        handler=lambda args: fake_outcome(structured={"got": args}),
    )
    notify = FakeToolDefinition(
        name="notify",
        read_only=None,
        idempotent=True,
        handler=lambda args: fake_outcome(text="notified"),
    )
    strict = FakeToolDefinition(
        name="strict",
        read_only=None,
        idempotent=None,
        handler=lambda args: fake_outcome(text="strap in"),
    )
    asking = FakeToolDefinition(
        name="ask",
        read_only=True,
        handler=lambda args: fake_outcome(text="never"),
        elicited=True,
    )
    return {"echo": echo, "wild": untyped, "bare": absent, "notify": notify, "strict": strict, "ask": asking}


def _server():
    tools = _builder_server_tools()
    server = FakeMcpServer(
        "srv",
        [tools["echo"], tools["wild"], tools["bare"], tools["notify"], tools["strict"], tools["ask"]],
    )
    return server, tools


def _registry_config(server, allow=("echo",)):
    return ToolRegistry(), [
        McpServerConfig("srv", FakeTransportFactory(server), allow_tools=allow)
    ]


def _ctx(sink=None):
    return ToolContext(run_id=DRY, node_id="n1", side_effect_sink=sink)


async def test_loader_refuses_silently_trusting_servers():
    server, _ = _server()
    registry = ToolRegistry()
    config = [McpServerConfig("srv", FakeTransportFactory(server))]
    with pytest.raises(McpInvalidConfigError):
        McpToolLoader(registry, config)


async def test_allow_undelisted_explicit_trust_registers_all():
    tools = _builder_server_tools()
    # 'strict' is policy-refused (no hints); its rejection has a dedicated test.
    trusted = FakeMcpServer(
        "srv",
        [tools["echo"], tools["wild"], tools["bare"], tools["notify"], tools["ask"]],
    )
    registry = ToolRegistry()
    factory = FakeTransportFactory(trusted)
    loader = McpToolLoader(
        registry,
        [McpServerConfig("srv", factory, allow_tools=None)],
        allow_undelisted=True,
    )
    snapshot = await loader.load()
    names = ("srv__ask", "srv__bare", "srv__echo", "srv__notify", "srv__wild")
    assert snapshot.registered_names == names
    await loader.close()


async def test_allow_tools_filter_registration():
    server, _ = _server()
    registry, config = _registry_config(server, allow=("echo",))
    loader = McpToolLoader(registry, config)
    snapshot = await loader.load()
    assert snapshot.registered_names == ("srv__echo",)
    with pytest.raises(ToolPermissionError):
        registry.get("srv__wild")
    await loader.close()


async def test_happy_snapshot_and_schemas():
    server, _ = _server()
    registry, config = _registry_config(server, allow=("echo", "wild", "bare"))
    loader = McpToolLoader(registry, config)
    snapshot = await loader.load()
    modes = {e.tool: e.schema_mode for e in snapshot.entries}
    assert modes == {"echo": "typed", "wild": "untyped", "bare": "absent"}
    # fingerprint determinism across independent loads
    server2, _ = _server()
    registry2, config2 = _registry_config(server2, allow=("echo", "wild", "bare"))
    snapshot2 = await McpToolLoader(registry2, config2).load()
    assert snapshot.fingerprint == snapshot2.fingerprint
    assert snapshots_same(snapshot, snapshot2)
    await loader.close()


def snapshots_same(a, b) -> bool:
    return a.fingerprint == b.fingerprint


async def test_same_raw_tool_name_across_servers_is_namespaced_not_colliding():
    server, tools = _server()
    noisy_server = FakeMcpServer("noisy", [tools["echo"]])
    registry = ToolRegistry()
    factory_a = FakeTransportFactory(server)
    factory_b = FakeTransportFactory(noisy_server)
    loader = McpToolLoader(
        registry,
        [
            McpServerConfig("srv", factory_a, allow_tools=("echo",)),
            McpServerConfig("noisy", factory_b, allow_tools=("echo",)),
        ],
    )
    snapshot = await loader.load()
    # Qualified names keep server namespaces isolated: no abort, both present.
    assert snapshot.registered_names == ("noisy__echo", "srv__echo")
    await loader.close()


async def test_load_failure_closes_all_transports():
    server, _ = _server()
    registry = ToolRegistry()
    factory = FakeTransportFactory(server)
    loader = McpToolLoader(registry, [McpServerConfig("srv", factory, allow_tools=("strict",))])
    with pytest.raises(McpToolError):
        await loader.load()
    assert factory.transports and factory.transports[0].is_connected is False
    assert loader.open_transport_count == 0


async def test_preexisting_local_registration_collision():
    server, _ = _server()
    registry = ToolRegistry()
    registry.register(FunctionTool("srv__echo", lambda args, ctx: "local", side_effect=False))  # placeholder needs input? FunctionTool: name, func, ...
    factory = FakeTransportFactory(server)
    loader = McpToolLoader(
        registry, [McpServerConfig("srv", factory, allow_tools=("echo",))]
    )
    with pytest.raises(ToolPermissionError):
        await loader.load()
    assert factory.transports[0].is_connected is False


async def test_non_idempotent_side_effect_tool_refused_and_closed():
    server, tools = _server()
    registry, config = _registry_config(server, allow=("strict",))
    loader = McpToolLoader(registry, config)
    with pytest.raises(McpToolError):
        await loader.load()
    factory = config[0].factory
    assert isinstance(factory, FakeTransportFactory)
    assert factory.transports[0].is_connected is False


async def test_typed_tool_goes_through_registry_validation():
    server, _ = _server()
    registry, config = _registry_config(server, allow=("echo",))
    loader = McpToolLoader(registry, config)
    await loader.load()
    res = await registry.invoke("srv__echo", {"msg": "hello"}, _ctx())
    assert res.ok and res.output == "echo:hello"
    with pytest.raises(ToolValidationError):
        await registry.invoke("srv__echo", {"msg": 4}, _ctx())
    await loader.close()


async def test_idempotent_side_effect_goes_through_sink():
    server, _ = _server()
    registry = ToolRegistry()
    factory = FakeTransportFactory(server)
    loader = McpToolLoader(
        registry, [McpServerConfig("srv", factory, allow_tools=("notify",))]
    )
    await loader.load()
    store = InMemoryCheckpointStore()
    sink = SideEffectSink(store, run_id=DRY, node_id="test-node", node_version="1")
    ctx = ToolContext(run_id=DRY, node_id="test-node", side_effect_sink=sink)
    res1 = await registry.invoke("srv__notify", {"token": "t", "id": 1}, ctx)
    res2 = await registry.invoke("srv__notify", {"token": "t", "id": 1}, ctx)
    assert res1.ok and res2.ok
    assert res1.output == "notified" and res2.output == "notified"
    assert sink.write_count == 1
    assert len(server.call_log) == 1
    await loader.close()


async def test_read_only_tool_bypasses_sink():
    server, _ = _server()
    registry = ToolRegistry()
    factory = FakeTransportFactory(server)
    loader = McpToolLoader(
        registry, [McpServerConfig("srv", factory, allow_tools=("echo",))]
    )
    await loader.load()
    store = InMemoryCheckpointStore()
    sink = SideEffectSink(store, run_id=DRY, node_id="test-node", node_version="1")
    ctx = ToolContext(run_id=DRY, node_id="test-node", side_effect_sink=sink)
    await registry.invoke("srv__echo", {"msg": "a"}, ctx)
    await registry.invoke("srv__echo", {"msg": "b"}, ctx)
    assert sink.write_count == 0
    assert len(server.call_log) == 2
    await loader.close()


async def test_elicitation_denied_via_registry():
    server, _ = _server()
    registry, config = _registry_config(server, allow=("ask",))
    loader = McpToolLoader(registry, config)
    await loader.load()
    ctx = _ctx()
    res = await registry.invoke("srv__ask", {}, ctx)
    assert res.ok is False
    assert res.error["kind"] == KIND_ELICITATION_DENIED
    assert res.error["retryable"] is False
    await loader.close()


async def test_loader_close_is_idempotent():
    server, _ = _server()
    registry, config = _registry_config(server, allow=("echo",))
    loader = McpToolLoader(registry, config)
    await loader.load()
    await loader.close()
    assert loader.open_transport_count == 0
    await loader.close()
    assert loader.open_transport_count == 0


async def test_loader_requires_at_least_one_server():
    with pytest.raises(McpInvalidConfigError):
        McpToolLoader(ToolRegistry(), [])


async def test_loader_rejects_duplicate_servers():
    server, _ = _server()
    with pytest.raises(McpInvalidConfigError):
        McpToolLoader(
            ToolRegistry(),
            [
                McpServerConfig("srv", FakeTransportFactory(server), allow_tools=("echo",)),
                McpServerConfig("srv", FakeTransportFactory(server), allow_tools=("echo",)),
            ],
        )
