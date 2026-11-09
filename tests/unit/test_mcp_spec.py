"""Phase 10 — MCP naming, server config validation and toolset snapshots."""

from __future__ import annotations

import pytest

from magent.mcp.errors import McpInvalidConfigError
from magent.mcp.spec import (
    McpServerConfig,
    McpToolDescriptor,
    McpToolEntry,
    McpToolsetSnapshot,
    qualify_tool_name,
    snapshots_consistent,
    validate_component,
)


async def test_qualify_tool_name():
    assert qualify_tool_name("nvd", "search") == "nvd__search"
    assert qualify_tool_name("a_b", "x-y") == "a_b__x-y"


async def test_invalid_components_rejected():
    for bad in ("", "with space", "slash/name", "dot.name", "é", "a" * 65):
        with pytest.raises(McpInvalidConfigError):
            validate_component(bad, "server")


async def test_qualify_tool_name_propagates_validation():
    with pytest.raises(McpInvalidConfigError):
        qualify_tool_name("", "tool")
    with pytest.raises(McpInvalidConfigError):
        qualify_tool_name("srv", "tool!bad")


def _descriptor(name="echo", read_only=None, idempotent=None, schema=None, description=""):
    return McpToolDescriptor(
        name=name,
        description=description,
        input_schema=schema,
        read_only_hint=read_only,
        idempotent_hint=idempotent,
    )


async def test_server_config_validation():
    def factory():
        return object()

    with pytest.raises(McpInvalidConfigError):
        McpServerConfig("", factory)
    with pytest.raises(McpInvalidConfigError):
        McpServerConfig("srv", None)
    with pytest.raises(McpInvalidConfigError):
        McpServerConfig("srv", factory, call_timeout=0.0)
    with pytest.raises(McpInvalidConfigError):
        McpServerConfig("srv", factory, allow_tools=())
    cfg = McpServerConfig("srv", factory, allow_tools=("echo",), call_timeout=None)
    assert cfg.allow_tools == ("echo",)


async def test_snapshot_fingerprint_and_ordering():
    e1 = McpToolEntry(
        registered_name="srv__zeta",
        server="srv",
        tool="zeta",
        schema_mode="typed",
        description="d1",
        side_effect=False,
        idempotent=False,
        read_only_hint=True,
    )
    e2 = McpToolEntry(
        registered_name="srv__alpha",
        server="srv",
        tool="alpha",
        schema_mode="untyped",
        description="d2",
        side_effect=True,
        idempotent=True,
        read_only_hint=None,
    )
    s1 = McpToolsetSnapshot(entries=(e1, e2))
    s2 = McpToolsetSnapshot(entries=(e2, e1))  # declaration order must not matter
    assert s1.fingerprint == s2.fingerprint
    assert s1.registered_names == ("srv__alpha", "srv__zeta")
    assert snapshots_consistent(s1, s2) is True


async def test_snapshot_fingerprint_sensitive_to_changes():
    base = McpToolDescriptor(
        name="echo", description="d", input_schema={"type": "object"}
    )
    entry_a = McpToolEntry(
        registered_name="srv__echo",
        server="srv",
        tool="echo",
        schema_mode="typed",
        description=base.description,
        side_effect=False,
        idempotent=False,
        read_only_hint=True,
    )
    entry_b = McpToolEntry(
        registered_name="srv__echo",
        server="srv",
        tool="echo",
        schema_mode="untyped",  # schema mode changed underneath
        description=base.description,
        side_effect=False,
        idempotent=False,
        read_only_hint=True,
    )
    entry_c = McpToolEntry(
        registered_name="srv__echo",
        server="srv",
        tool="echo",
        schema_mode="typed",
        description=base.description + "!",  # description changed underneath
        side_effect=False,
        idempotent=False,
        read_only_hint=True,
    )
    a = McpToolsetSnapshot(entries=(entry_a,))
    b = McpToolsetSnapshot(entries=(entry_b,))
    c = McpToolsetSnapshot(entries=(entry_c,))
    assert not snapshots_consistent(a, b)
    assert not snapshots_consistent(a, c)


async def test_snapshot_record_round_trip():
    entry = McpToolEntry(
        registered_name="srv__echo",
        server="srv",
        tool="echo",
        schema_mode="typed",
        description="d",
        side_effect=False,
        idempotent=False,
        read_only_hint=True,
    )
    snapshot = McpToolsetSnapshot(entries=(entry,))
    record = snapshot.to_record()
    assert record["fingerprint"] == snapshot.fingerprint
    assert record["tools"][0]["registered_name"] == "srv__echo"
    assert snapshot.server_names() == ("srv",)
