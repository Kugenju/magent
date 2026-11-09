"""Real streamable-HTTP transport (P10.2 — placeholder, lazily SDK-gated).

Same contract as ``magent.mcp.stdio``: the transport seam and the offline double
exist in P10.1; this module is the reserved wiring point for the real HTTP
transport (kept disabled by default — SSRF surface, see
``docs/architecture/NETWORK_POLICY.md``).

Implementing P10.2 must:
- lazily import the SDK inside the factory (no top-level network imports);
- enforce an explicit endpoint allowlist at the caller (loader/CLI) level;
- raise only classified errors from ``magent.mcp.errors``.
"""

from __future__ import annotations

from typing import Any

from magent.mcp.errors import McpInvalidConfigError
from magent.mcp.stdio import require_mcp_sdk


def http_transport(
    base_url: str | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> Any:
    """Build a real streamable-HTTP transport. Planned for P10.2.

    The endpoint allowlist must be enforced by the caller before invocation;
    HTTP transports stay disabled by default (SSRF surface).
    """
    require_mcp_sdk()
    raise McpInvalidConfigError(
        "the real HTTP transport lands in P10.2; until then use "
        "magent.mcp.fake.InMemoryMcpTransport for all offline flows"
    )
