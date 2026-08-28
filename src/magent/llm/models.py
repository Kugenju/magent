"""LLM provider domain models (phase 6).

Only structured models cross the provider boundary; vendor SDK types are never
allowed to leak into ``magent`` core. The core depends on the abstract
:class:`LLMProvider` protocol and the deterministic :class:`FakeProvider`, so it
installs and runs with no API key and no network.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from magent.core.errors import MagentError


class LLMError(MagentError):
    """Base class for LLM failures."""


class LLMRateLimitError(LLMError):
    """429 / transient quota failure — retryable."""


class LLMAuthError(LLMError):
    """Authentication / authorization failure — not retryable."""


class LLMInvalidParamError(LLMError):
    """Bad request parameters — not retryable."""


class LLMContentRefusedError(LLMError):
    """Provider refused the prompt or output — not retryable."""


class ChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMRequest(BaseModel):
    """A provider-agnostic completion request.

    ``tools`` carries only safe tool metadata (names/versions), never the
    executable objects. ``response_schema`` is a pydantic model class used for
    validation of the returned message and is intentionally not serialized.
    """

    messages: list[ChatMessage]
    model: str = "fake"
    temperature: float = 0.0
    tools: list[dict[str, Any]] = Field(default_factory=list)
    response_schema: Any = None  # type[BaseModel] | None

    def with_tools(self, tool_specs: list) -> "LLMRequest":
        self.tools = [t.to_metadata() for t in tool_specs]
        return self


class LLMResponse(BaseModel):
    message: ChatMessage
    finish_reason: str = "stop"
    usage: Usage = Field(default_factory=Usage)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    def to_report_meta(self) -> dict[str, Any]:
        return {
            "model": self.raw_metadata.get("model"),
            "provider_version": self.raw_metadata.get("provider_version"),
            "finish_reason": self.finish_reason,
            "usage": self.usage.model_dump(),
        }
