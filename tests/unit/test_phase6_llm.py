"""Phase 6 — llm layer tests."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from magent.tools.models import ToolSpec
from magent.llm.models import (
    ChatMessage,
    LLMError,
    LLMInvalidParamError,
    LLMRequest,
    LLMResponse,
    Usage,
)
from magent.llm.provider import FakeProvider, get_llm_provider, map_provider_error


async def test_fake_provider_echo():
    p = FakeProvider()
    resp = await p.complete(LLMRequest(messages=[ChatMessage(role="user", content="hi")]))
    assert resp.message.content == "echo:hi"


async def test_fake_provider_async_complete():
    p = FakeProvider()
    resp = await p.complete(LLMRequest(messages=[ChatMessage(role="user", content="x")]))
    assert resp.finish_reason == "stop"
    assert resp.usage.total_tokens >= 0


async def test_fake_provider_scripted_responses_cycle():
    r1 = LLMResponse(message=ChatMessage(role="assistant", content="a"))
    r2 = LLMResponse(message=ChatMessage(role="assistant", content="b"))
    p = FakeProvider(responses=[r1, r2])
    assert (await p.complete(LLMRequest(messages=[]))).message.content == "a"
    assert (await p.complete(LLMRequest(messages=[]))).message.content == "b"
    assert (await p.complete(LLMRequest(messages=[]))).message.content == "a"  # cycles


async def test_fake_provider_handler():
    p = FakeProvider(handler=lambda req: LLMResponse(message=ChatMessage(role="assistant", content="handled")))
    assert (await p.complete(LLMRequest(messages=[]))).message.content == "handled"


def test_get_llm_provider_fake():
    assert isinstance(get_llm_provider("fake"), FakeProvider)


def test_get_llm_provider_unknown():
    with pytest.raises(LLMInvalidParamError):
        get_llm_provider("nope")


def test_get_llm_provider_openai_isolated():
    import importlib.util

    if importlib.util.find_spec("openai") is None:
        with pytest.raises(LLMError):
            get_llm_provider("openai", api_key="k")
    else:
        from magent.llm.models import LLMAuthError

        with pytest.raises(LLMAuthError):
            get_llm_provider("openai")
        prov = get_llm_provider("openai", api_key="x")
        assert prov.name == "openai"


def test_request_with_tools_metadata():
    req = LLMRequest(messages=[])
    req.with_tools([ToolSpec("web_search", side_effect=True, idempotent=True)])
    assert req.tools == [{"name": "web_search", "version": "1", "description": "", "side_effect": True, "idempotent": True}]


def test_response_to_report_meta():
    resp = LLMResponse(
        message=ChatMessage(role="assistant", content="c"),
        usage=Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        raw_metadata={"model": "m", "provider_version": "1"},
    )
    meta = resp.to_report_meta()
    assert meta["usage"]["total_tokens"] == 3 and meta["model"] == "m"


def test_map_provider_error_classification():
    assert map_provider_error(Exception("401 auth")).__class__.__name__ == "LLMAuthError"
    assert map_provider_error(Exception("rate 429")).__class__.__name__ == "LLMRateLimitError"
    assert map_provider_error(Exception("invalid 400")).__class__.__name__ == "LLMInvalidParamError"
    assert map_provider_error(Exception("openai error")).__class__.__name__ == "LLMError"
