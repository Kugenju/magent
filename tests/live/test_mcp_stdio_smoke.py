"""P10.2 live smoke — REAL stdio MCP server through the real magent pipeline.

Runs the official-SDK server in ``tools/mcp_example_server.py`` as an actual
process, drives it through ``StdioMcpTransport`` -> ``McpToolLoader`` ->
``ToolRegistry`` -> ``McpToolProxy``, and touches the public OSV.dev API from
the server process (VulnTell-relevant, read-only).

Opt-in only:
    MAGENT_RUN_LIVE=1 pytest tests/live -q

Without the env var every test here SKIPS; the offline CI gate never spawns
processes or touches the network.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = ROOT / "tools" / "mcp_example_server.py"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("MAGENT_RUN_LIVE"),
        reason="live tests need MAGENT_RUN_LIVE=1 (offline CI gate stays closed)",
    ),
]
pytest.importorskip("mcp", reason="official MCP SDK (extra `magent[mcp]`) not installed")

from magent.mcp.loader import McpToolLoader  # noqa: E402
from magent.mcp.spec import McpServerConfig  # noqa: E402
from magent.mcp.stdio import stdio_transport  # noqa: E402
from magent.tools.context import ToolContext  # noqa: E402
from magent.tools.models import ToolPermissionError, ToolValidationError  # noqa: E402
from magent.tools.registry import ToolRegistry  # noqa: E402

ALLOWED = ("echo", "profile_query", "osv_lookup")


def _proxy_env() -> dict[str, str]:
    """Forward explicit proxy settings into the server process (if any)."""
    forwarded: dict[str, str] = {}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        value = os.environ.get(key)
        if value:
            forwarded[key] = value
    return forwarded


def _make_server_factory(errlog: Any) -> Callable[[], Any]:
    return lambda: stdio_transport(
        sys.executable,
        args=(str(SERVER_SCRIPT),),
        env=_proxy_env(),
        errlog=errlog,
    )


def _ctx() -> ToolContext:
    return ToolContext(run_id="live-r1", node_id="live-n1")


async def test_real_stdio_pipeline(tmp_path):
    """Spawn -> initialize -> list -> register -> invoke, entirely real."""
    errlog = (tmp_path / "server_stderr.log").open("a", encoding="utf-8")
    try:
        registry = ToolRegistry()
        config = McpServerConfig(
            "demo",
            _make_server_factory(errlog),
            allow_tools=ALLOWED,
            call_timeout=60.0,
        )
        loader = McpToolLoader(registry, [config])
        snapshot = await loader.load()
        try:
            assert "demo__echo" in snapshot.registered_names
            assert "demo__profile_query" in snapshot.registered_names
            assert "demo__osv_lookup" in snapshot.registered_names

            # 1) deterministic offline tool through the full policy pipeline.
            # FastMCP (SDK 1.30) wraps scalar returns in structuredContent
            # `{"result": ...}`; the proxy prefers structured passthrough.
            res = await registry.invoke("demo__echo", {"msg": "ping"}, _ctx())
            assert res.ok is True
            assert "echo:ping" in str(res.output)
            assert res.meta["transport"] == "mcp"
            assert res.meta["registered_name"] == "demo__echo"

            # 2) typed schema conversion against the REAL server schema:
            #    enum + default + optional.
            res2 = await registry.invoke(
                "demo__profile_query", {"service": "osv", "max_results": 2}, _ctx()
            )
            assert res2.ok is True
            assert "profile[osv]" in str(res2.output)
            assert "batch=2" in str(res2.output)

            # enum violations are rejected by the registry (same pipeline as
            # local tools), from the server-declared JSON Schema.
            with pytest.raises(ToolValidationError):
                await registry.invoke(
                    "demo__profile_query", {"service": "xml"}, _ctx()
                )

            # unknown tool names never reach the server.
            with pytest.raises(ToolPermissionError):
                await registry.invoke("demo__nope", {}, _ctx())
        finally:
            await loader.close()
        assert snapshot.fingerprint  # deterministic fingerprint material exists
    finally:
        errlog.close()


async def test_real_server_side_failure_is_uniform(tmp_path):
    """An in-server exception (bad OSV id) reaches the client as kind=permanent."""
    errlog = (tmp_path / "server_stderr.log").open("a", encoding="utf-8")
    try:
        registry = ToolRegistry()
        config = McpServerConfig(
            "demo",
            _make_server_factory(errlog),
            allow_tools=("osv_lookup",),
            call_timeout=60.0,
        )
        loader = McpToolLoader(registry, [config])
        await loader.load()
        try:
            res = await registry.invoke(
                "demo__osv_lookup", {"vuln_id": "definitely-not-a-cve-000123"}, _ctx()
            )
            if not res.ok and "network" in str(res.error.get("message", "")).lower():
                pytest.skip("network unreachable; cannot exercise OSV 404 path")
            assert res.ok is False
            assert res.error["kind"] == "permanent"
            assert res.error["retryable"] is False
            assert res.error["server"] == "demo"
        finally:
            await loader.close()
    finally:
        errlog.close()


async def test_real_osv_read(tmp_path):
    """Real read-only network read through the server process (VulnTell source)."""
    errlog = (tmp_path / "server_stderr.log").open("a", encoding="utf-8")
    try:
        registry = ToolRegistry()
        config = McpServerConfig(
            "demo",
            _make_server_factory(errlog),
            allow_tools=("osv_lookup",),
            call_timeout=60.0,
        )
        loader = McpToolLoader(registry, [config])
        await loader.load()
        try:
            res = await registry.invoke(
                "demo__osv_lookup", {"vuln_id": "CVE-2024-3094"}, _ctx()
            )
            if not res.ok:
                # Live network may be unavailable (CI/offline proxy); skip soft.
                pytest.skip(f"OSV endpoint unreachable: {res.error.get('message', '')[:120]}")
            text = str(res.output)
            assert "OSV CVE-2024-3094" in text
            assert res.meta["transport"] == "mcp"
        finally:
            await loader.close()
    finally:
        errlog.close()
