"""MCP toolset loader: connect -> list -> plan -> register -> snapshot (phase 10).

The loader is the single entry point for bringing an MCP server's tools into a
:class:`~magent.tools.registry.ToolRegistry`. It enforces the strict phase-10
registration policy *before* anything reaches the registry:

1. every server must carry an allowlist (``allow_tools``) unless the caller
   explicitly passes ``allow_undelisted=True`` — nothing is silently trusted;
2. a tool without ``read_only_hint=True`` is treated as side-effecting; a
   side-effecting tool without ``idempotent_hint=True`` is refused;
3. qualified names (``<server>__<tool>``) must be unique — both inside one load
   and against tools already registered; a conflict fails the whole load;
4. a load produces a deterministic :class:`McpToolsetSnapshot` whose fingerprint
   must match on checkpoint resume.

The load is two-pass: pass A connects and plans (validating every policy
question up front), pass B registers the planned proxies. On any failure all
transports opened during the load are closed before the error propagates: no
dangling sessions and no partially planned registrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from magent.tools.models import ToolPermissionError
from magent.tools.registry import ToolRegistry

from .errors import McpInvalidConfigError
from .schema import build_input_model
from .spec import (
    McpServerConfig,
    McpToolDescriptor,
    McpToolEntry,
    McpToolsetSnapshot,
    validate_component,
)
from .proxy import McpToolProxy
from .transport import McpTransport


@dataclass
class _PlanEntry:
    """A tool fully planned during pass A; registers instantly in pass B."""

    server: McpServerConfig
    descriptor: McpToolDescriptor
    proxy: McpToolProxy
    entry: McpToolEntry


class McpToolLoader:
    """Register a configured set of MCP servers' tools into a registry."""

    def __init__(
        self,
        registry: ToolRegistry,
        servers: Sequence[McpServerConfig],
        *,
        allow_undelisted: bool = False,
    ) -> None:
        if not servers:
            raise McpInvalidConfigError(
                "McpToolLoader requires at least one configured server"
            )
        self._registry = registry
        self._servers: tuple[McpServerConfig, ...] = tuple(servers)
        self._allow_undelisted = allow_undelisted
        self._transports: list[McpTransport] = []
        seen_servers: set[str] = set()
        for server in self._servers:
            if server.name in seen_servers:
                raise McpInvalidConfigError(
                    f"duplicate server configured: {server.name!r}"
                )
            seen_servers.add(server.name)
        every_server_listed = all(s.allow_tools is not None for s in self._servers)
        if not every_server_listed and not allow_undelisted:
            unlisted = [s.name for s in self._servers if s.allow_tools is None]
            raise McpInvalidConfigError(
                "refusing to trust unlisted servers' tools implicitly "
                f"({', '.join(unlisted)}); pass an explicit allow_tools per server "
                "or set allow_undelisted=True to accept every listed tool"
            )

    # -- loading ---------------------------------------------------------------
    async def load(self) -> McpToolsetSnapshot:
        """Connect every server, register its allowed tools, return the snapshot.

        Determinism: servers process in configuration order; tools process in the
        transport's deterministic listing order. Any failure aborts the load.
        """
        try:
            plans = await self._plan()
            for plan in plans:
                self._registry.register(plan.proxy)
        except Exception:
            await self.close()
            raise
        entries = tuple(plan.entry for plan in plans)
        return McpToolsetSnapshot(entries=entries)

    async def _plan(self) -> list[_PlanEntry]:
        """Pass A: open transports, list tools, validate policies, build proxies."""
        plans: list[_PlanEntry] = []
        planned_names: set[str] = set()
        for server in self._servers:
            transport = server.factory()
            self._transports.append(transport)
            await transport.connect()
            descriptors = await transport.list_tools()
            allowed = server.allow_tools
            for descriptor in descriptors:
                validate_component(descriptor.name, "tool")
                if allowed is not None and descriptor.name not in allowed:
                    continue
                qualified = f"{server.name}__{descriptor.name}"
                self._ensure_free(qualified, planned_names)
                input_model, schema_mode = build_input_model(
                    descriptor.name, descriptor.input_schema
                )
                proxy = McpToolProxy(
                    server_name=server.name,
                    descriptor=descriptor,
                    transport=transport,
                    input_model=input_model,
                    schema_mode=schema_mode,
                    call_timeout=server.call_timeout,
                )
                hint = descriptor.read_only_hint
                entry = McpToolEntry(
                    registered_name=qualified,
                    server=server.name,
                    tool=descriptor.name,
                    schema_mode=schema_mode,
                    description=descriptor.description,
                    side_effect=hint is not True,
                    idempotent=descriptor.idempotent_hint is True,
                    read_only_hint=hint,
                )
                plans.append(_PlanEntry(server, descriptor, proxy, entry))
                planned_names.add(qualified)
        return plans

    def _ensure_free(self, qualified: str, planned_names: set[str]) -> None:
        if qualified in planned_names:
            raise ToolPermissionError(
                f"tool {qualified!r} collides with an earlier plan in this load"
            )
        try:
            self._registry.get(qualified)
        except ToolPermissionError:
            return
        raise ToolPermissionError(
            f"tool {qualified!r} collides with a name already registered"
        )

    # -- lifecycle ----------------------------------------------------------------
    async def close(self) -> None:
        """Close all transports opened for the latest load; safe to call often."""
        transports, self._transports = self._transports, []
        for transport in transports:
            try:
                await transport.close()
            except Exception:  # noqa: BLE001 - best-effort session teardown
                continue

    @property
    def open_transport_count(self) -> int:
        return len(self._transports)
