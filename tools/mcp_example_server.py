"""Real local MCP server for P10.2 stdio verification (official SDK / FastMCP).

run with:
    python tools/mcp_example_server.py          # stdio transport

Provides three read-only tools (annotations on the server side, so the magent
loader accepts them under the strict phase-10 policy):

- ``echo(msg)``            deterministic echo — proves the end-to-end pipeline
                           (spawn -> initialize -> list_tools -> call_tool)
                           without any network;
- ``profile_query(...)``   enum + default + optional schema shapes — proves the
                           typed schema conversion against a *real* server;
- ``osv_lookup(vuln_id)``  hits the public OSV.dev API (VulnTell is registered
                           as a downstream source) — a real read-only network
                           read from the SERVER process; also an exercise of a
                           server-side tool failure (network error -> isError).
- ``osv_get_payload(id)``  the same record as RAW json (structured content) —
                           the tool backing VulnTell's MCP collection path and
                           the dual-path consistency check.

stderr stays ASCII-only (Windows cp936 pipe decoding in the client would break
on non-ASCII logs).
"""

from __future__ import annotations

import enum
import json
import urllib.parse
import urllib.request

import mcp.types as types
from mcp.server.fastmcp import FastMCP

APP = FastMCP("vulntell-demo")

_READONLY = types.ToolAnnotations(readOnlyHint=True)


class Service(str, enum.Enum):
    """Registered VulnTell collection sources (becomes a real JSON-Schema enum)."""

    osv = "osv"
    nvd = "nvd"
    github = "github"


@APP.tool(annotations=_READONLY)
def echo(msg: str) -> str:
    """Echo ``msg`` back as ``echo:<msg>`` (deterministic, offline)."""
    return f"echo:{msg}"


@APP.tool(annotations=_READONLY)
def profile_query(service: Service, max_results: int = 5) -> str:
    """Describe the registered collection profile for one VulnTell source.

    ``service`` is an enum (osv / nvd / github); ``max_results`` defaults to 5.
    Purely local: exercises enum/default/optional schema conversion.
    """
    key = service.value if isinstance(service, Service) else str(service)
    budgets = {"osv": 30, "nvd": 20, "github": 45}
    if key not in budgets:
        return f"unknown service {key!r}"
    return f"profile[{key}] batch={min(max_results, budgets[key])} results"


@APP.tool(annotations=_READONLY)
def osv_lookup(vuln_id: str) -> str:
    """Read one vulnerability record from the public OSV.dev API (read-only).

    A network failure inside the tool shows up on the client as an
    ``isError`` result with kind ``permanent`` — one uniform client shape.
    """
    url = "https://api.osv.dev/v1/vulns/" + urllib.parse.quote(vuln_id, safe="")
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "vulntell-demo/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    record_id = data.get("id", "?")
    aliases = ", ".join(data.get("aliases", [])[:4]) or "-"
    summary = (data.get("summary") or "")[:200]
    return f"OSV {record_id} | aliases: {aliases} | {summary}".strip()


@APP.tool(annotations=_READONLY)
def osv_get_payload(vuln_id: str) -> dict:
    """Read one RAW OSV.dev vulnerability record (read-only, structured).

    Returns the untouched OSV JSON so the VulnTell MCP collection path and
    the direct-HTTP path can be compared on identical bytes (dual-path
    consistency check in the daily briefing workflow). Structured content:
    FastMCP wraps the dict under ``{"result": ...}`` on the client side.
    """
    url = "https://api.osv.dev/v1/vulns/" + urllib.parse.quote(vuln_id, safe="")
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "vulntell-daily/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    record: dict = json.loads(body)
    if not record.get("id"):
        raise ValueError(f"OSV response missing id for {vuln_id!r}")
    return record


if __name__ == "__main__":
    APP.run()
