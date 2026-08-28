"""Tool protocol domain models (phase 6).

Tools are the only sanctioned way for an Agent to perform a side effect or a
structured computation outside the framework state. They never mutate the
framework ``State`` directly; they return a :class:`ToolResult` and the Agent
decides how to turn that into an ``AgentResult``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from magent.core.errors import MagentError


class ToolError(MagentError):
    """Base class for tool failures."""


class ToolPermissionError(ToolError):
    """Tool is not registered or not on the allowlist."""


class ToolValidationError(ToolError):
    """Input or output failed schema / policy validation."""


class ToolTimeoutError(ToolError):
    """Tool exceeded its configured timeout."""


class ToolResult(BaseModel):
    """Structured, serializable result of a tool call.

    ``output`` carries the primary payload (any JSON-able value). ``structured``
    is an optional machine-readable dict, ``error`` a structured failure and
    ``meta`` holds redacted observability metadata (timings, provider, sizes).
    """

    output: Any = None
    structured: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    meta: dict[str, Any] | None = Field(default=None)

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, output: Any = None, structured: dict | None = None, meta: dict | None = None) -> "ToolResult":
        return cls(output=output, structured=structured, meta=meta)

    @classmethod
    def failure(cls, error: dict[str, Any], meta: dict | None = None) -> "ToolResult":
        return cls(error=error, meta=meta)


class ToolSpec:
    """Immutable description of a tool: identity, schema and side-effect policy.

    ``input_model`` / ``output_model`` are pydantic model classes used for
    validation; they are not serialized with the spec (only the safe metadata
    is exported for checkpoint compatibility).
    """

    def __init__(
        self,
        name: str,
        *,
        version: str = "1",
        description: str = "",
        input_model=None,
        output_model=None,
        side_effect: bool = False,
        idempotent: bool = False,
    ) -> None:
        if not name:
            raise ToolValidationError("tool name must be non-empty")
        self.name = name
        self.version = version
        self.description = description
        self.input_model = input_model
        self.output_model = output_model
        self.side_effect = side_effect
        self.idempotent = idempotent

    def to_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "side_effect": self.side_effect,
            "idempotent": self.idempotent,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ToolSpec(name={self.name!r}, version={self.version!r})"
