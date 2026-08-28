"""Optional OpenAI adapter (phase 6, vendor SDK isolated).

This module is intentionally *not* imported by the framework core. It is only
loaded when an explicit ``get_llm_provider("openai", ...)`` call is made, so a
missing ``openai`` package never breaks ``import magent``. The adapter maps
provider errors onto the structured :mod:`magent.llm.models` error classes.
"""

from __future__ import annotations

from typing import Any

from .models import (
    ChatMessage,
    LLMAuthError,
    LLMError,
    LLMInvalidParamError,
    LLMRequest,
    LLMResponse,
    Usage,
)
from .provider import map_provider_error


class OpenAIChatProvider:
    name = "openai"
    version = "1"

    def __init__(self, *, api_key: str | None = None, model: str = "gpt-4o-mini", **kwargs: Any) -> None:
        try:
            from openai import AsyncOpenAI  # lazy import; not a core dependency
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise LLMError(
                "openai", "", "the 'openai' package is not installed", cause=exc
            )
        if api_key is None:
            raise LLMAuthError("openai", "", "api_key is required for the openai provider")
        self._client = AsyncOpenAI(api_key=api_key, **kwargs)
        self._model = model

    async def complete(self, request: LLMRequest, context: Any = None) -> LLMResponse:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[m.model_dump(exclude_none=True) for m in request.messages],  # type: ignore[misc]
                temperature=request.temperature,
                tools=request.tools or None,  # type: ignore[arg-type]
            )
        except Exception as exc:  # pragma: no cover - requires network/key
            raise map_provider_error(exc)

        choice = resp.choices[0]
        msg = choice.message
        return LLMResponse(
            message=ChatMessage(
                role=msg.role,
                content=msg.content or "",
                tool_calls=[tc.model_dump() for tc in (msg.tool_calls or [])] or None,
            ),
            finish_reason=choice.finish_reason or "stop",
            usage=Usage(
                prompt_tokens=getattr(resp.usage, "prompt_tokens", 0),
                completion_tokens=getattr(resp.usage, "completion_tokens", 0),
                total_tokens=getattr(resp.usage, "total_tokens", 0),
            ),
            raw_metadata={"model": self._model, "provider_version": self.version},
        )
