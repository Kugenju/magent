"""MCP naming, server configuration and toolset snapshot (phase 10).

The loader gives every MCP tool a deterministic, collision-free registry name
``<server>__<tool>`` and freezes the imported toolset into a snapshot whose
fingerprint must stay identical across checkpoint resume (一致性哲学: 与恢复基线
不符就明确拒绝，绝不隐式迁移).

Transport objects are *never* stored in the config: a ``factory`` callable
creates one per load, so a frozen ``McpServerConfig`` stays serializable.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from magent.checkpoint.models import canonical_json, checksum_of

from .errors import McpInvalidConfigError

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a runtime import cycle
    from .transport import McpTransport

# Name component validation (SEP-986-style conservative subset):
# a component must be ASCII alnum/underscore/hyphen, non-empty, bounded length.
_COMPONENT_MAX = 64
_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Client-side annotation hints carried on an MCP tool definition.
HINT_READ_ONLY = "read_only_hint"
HINT_IDEMPOTENT = "idempotent_hint"
HINT_DESTRUCTIVE = "destructive_hint"


def validate_component(name: str, what: str) -> str:
    """Validate a naming component (server or tool) and return it unchanged."""
    if not name:
        raise McpInvalidConfigError(f"{what} name must not be empty")
    if len(name) > _COMPONENT_MAX:
        raise McpInvalidConfigError(
            f"{what} name exceeds {_COMPONENT_MAX} characters: {name!r}"
        )
    if not _COMPONENT_RE.match(name):
        raise McpInvalidConfigError(
            f"{what} name must match {_COMPONENT_RE.pattern!r}, got {name!r}"
        )
    return name


def qualify_tool_name(server_name: str, tool_name: str) -> str:
    """Return the collision-free registry name ``<server>__<tool>``."""
    validate_component(server_name, "server")
    validate_component(tool_name, "tool")
    return f"{server_name}__{tool_name}"


@dataclass(frozen=True)
class McpToolDescriptor:
    """SDK-agnostic description of one tool listed by an MCP server.

    ``input_schema`` is the raw JSON Schema dict (possibly ``None``). The
    annotation hints follow the MCP tool-annotation vocabulary; ``None``
    means "declared nowhere" and is treated with the strict side-effect
    policy (see ``loader``).
    """

    name: str
    description: str = ""
    input_schema: Mapping[str, Any] | None = None
    output_schema: Mapping[str, Any] | None = None
    read_only_hint: bool | None = None
    idempotent_hint: bool | None = None
    destructive_hint: bool | None = None

    @property
    def schema_mode_hint(self) -> str:
        return "absent" if self.input_schema in (None, {}) else "present"


@dataclass(frozen=True)
class McpServerConfig:
    """Immutable per-server configuration (no live transport inside).

    ``factory`` must return a fresh, unconnected ``McpTransport`` each load.

    ``allow_tools`` is the server-level allowlist of *raw* tool names; ``None``
    means "trust every tool this server lists", which is only accepted by the
    loader when the caller passes ``allow_undelisted=True`` explicitly.
    """

    name: str
    factory: Callable[[], "McpTransport"]
    allow_tools: tuple[str, ...] | None = None
    call_timeout: float | None = 30.0

    def __post_init__(self) -> None:
        validate_component(self.name, "server")
        if not callable(self.factory):
            raise McpInvalidConfigError(f"server {self.name!r}: factory must be callable")
        if self.call_timeout is not None and self.call_timeout <= 0:
            raise McpInvalidConfigError(
                f"server {self.name!r}: call_timeout must be positive or None"
            )
        if self.allow_tools is not None:
            if len(self.allow_tools) == 0:
                raise McpInvalidConfigError(
                    f"server {self.name!r}: allow_tools=[] denies registration; "
                    "avoid listing this server instead"
                )
            for tool in self.allow_tools:
                validate_component(tool, "tool")


@dataclass(frozen=True)
class McpToolEntry:
    """One registered tool inside a snapshot (resume-comparable identity)."""

    registered_name: str
    server: str
    tool: str
    schema_mode: str  # "absent" | "typed" | "untyped"
    description: str = ""
    side_effect: bool = False
    idempotent: bool = False
    read_only_hint: bool | None = None

    def to_record(self) -> dict[str, Any]:
        return dict(dataclasses.asdict(self))


@dataclass(frozen=True)
class McpToolsetSnapshot:
    """Frozen view of the imported MCP toolset for one run.

    The ``fingerprint`` is stable across identical imports (same servers,
    same tools, same schemas/hints) and must be re-verified on resume:
    a mismatch means the toolset changed underneath the run.
    """

    entries: tuple[McpToolEntry, ...]
    fingerprint: str = field(default="")

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.entries, key=lambda e: e.registered_name))
        object.__setattr__(self, "entries", ordered)
        payload = {
            "version": 1,
            "tools": [e.to_record() for e in ordered],
        }
        digest = checksum_of(canonical_json(payload))[:16]
        object.__setattr__(self, "fingerprint", digest)

    @property
    def registered_names(self) -> tuple[str, ...]:
        return tuple(e.registered_name for e in self.entries)

    def server_names(self) -> tuple[str, ...]:
        seen: list[str] = []
        for e in self.entries:
            if e.server not in seen:
                seen.append(e.server)
        return tuple(seen)

    def to_record(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "tools": [e.to_record() for e in self.entries],
        }


def snapshots_consistent(a: McpToolsetSnapshot, b: McpToolsetSnapshot) -> bool:
    """Return True when two snapshots may share a run (resume/replay check)."""
    return a.fingerprint == b.fingerprint


def normalize_allowlist(raw: Sequence[str] | None) -> tuple[str, ...] | None:
    """Validate/normalize a sequence of tool names into a tuple, or ``None``."""
    if raw is None:
        return None
    values = tuple(raw)
    return values or None
