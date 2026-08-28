"""LLM provider protocol, deterministic Fake provider and factory (phase 6)."""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from .models import (
    ChatMessage,
    LLMAuthError,
    LLMError,
    LLMInvalidParamError,
    LLMRequest,
    LLMResponse,
    Usage,
)


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    version: str

    async def complete(self, request: LLMRequest, context: Any = None) -> LLMResponse: ...


class FakeProvider:
    """Deterministic, offline provider.

    - With ``responses`` it returns them in order, cycling if exhausted.
    - With ``handler`` it delegates to ``handler(request) -> LLMResponse``.
    - Otherwise it echoes a stable string derived from the last user message.

    No network, no API key, no vendor SDK import.
    """

    name = "fake"
    version = "1"

    def __init__(
        self,
        *,
        responses: list[LLMResponse] | None = None,
        handler: Callable[[LLMRequest], LLMResponse] | None = None,
        echo: bool = True,
    ) -> None:
        self._responses = responses
        self._handler = handler
        self._echo = echo
        self._idx = 0

    async def complete(self, request: LLMRequest, context: Any = None) -> LLMResponse:
        if self._handler is not None:
            return self._handler(request)
        if self._responses:
            resp = self._responses[self._idx % len(self._responses)]
            self._idx += 1
            return resp
        if self._echo:
            last_user = next(
                (m.content for m in reversed(request.messages) if m.role == "user"),
                "",
            )
            return LLMResponse(
                message=ChatMessage(role="assistant", content=f"echo:{last_user}"),
                finish_reason="stop",
                usage=Usage(prompt_tokens=len(last_user), completion_tokens=len(last_user)),
                raw_metadata={"model": request.model, "provider_version": self.version},
            )
        return LLMResponse(message=ChatMessage(role="assistant", content=""))


def get_llm_provider(name: str = "fake", **kwargs: Any) -> LLMProvider:
    """Construct an LLM provider by name.

    The ``"fake"`` provider is always available. Vendor adapters are imported
    lazily so the core never depends on a third-party SDK.
    """
    if name == "fake":
        return FakeProvider(**kwargs)
    if name == "openai":
        from .openai_adapter import OpenAIChatProvider

        return OpenAIChatProvider(**kwargs)
    raise LLMInvalidParamError(f"unknown LLM provider {name!r}")


def map_provider_error(exc: Exception) -> LLMError:
    """Map a generic provider error to a structured :class:`LLMError`."""
    msg = str(exc)
    lowered = msg.lower()
    if "401" in msg or "auth" in lowered:
        return LLMAuthError("llm auth failed", "", msg, cause=exc)
    if "429" in msg or "rate" in lowered:
        from .models import LLMRateLimitError

        return LLMRateLimitError("llm rate limited", "", msg, cause=exc)
    if "400" in msg or "invalid" in lowered:
        return LLMInvalidParamError("llm invalid param", "", msg, cause=exc)
    return LLMError("llm error", "", msg, cause=exc)
