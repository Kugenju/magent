"""Phase 6 demonstration: tools, LLM provider and middleware.

Runs fully offline (no API key, no network) using the deterministic
``FakeProvider``. It shows:

* registering schema-validated sync/async tools behind an allowlist,
* routing a side-effect tool through ``SideEffectSink`` for idempotency,
* tool timeout / size-limit enforcement,
* composing logging + rate-limit + redaction middleware over agents,
* issuing a tool-calling LLM request with the structured ``FakeProvider``.

Run with::

    python -m examples.phase6_tools_llm_middleware
"""

from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel

from magent.checkpoint import InMemoryCheckpointStore, SideEffectSink
from magent.core import BaseAgent, Runtime
from magent.llm import ChatMessage, FakeProvider, LLMRequest
from magent.middleware import (
    LoggingMiddleware,
    MiddlewareAgent,
    RateLimitMiddleware,
    RedactionMiddleware,
)
from magent.tools import FunctionTool, ToolContext, ToolRegistry, tool


class AddIn(BaseModel):
    a: int
    b: int


class AddOut(BaseModel):
    sum: int


class AppState(BaseModel):
    total: int = 0


class Adder(BaseAgent):
    """Adds two numbers using a validated tool behind the registry."""

    def __init__(self, registry: ToolRegistry, sink: SideEffectSink | None = None) -> None:
        super().__init__("adder")
        self._registry = registry
        self._sink = sink

    async def run(self, state: AppState, runtime: Runtime) -> AppState:
        ctx = ToolContext(
            run_id=runtime.run_id,
            node_id=self.name,
            side_effect_sink=self._sink,
        )
        res = await self._registry.invoke("add", {"a": state.total, "b": 1}, ctx)
        assert res.ok, res.error
        return AppState(total=res.output.sum)


def _build_registry() -> ToolRegistry:
    reg = ToolRegistry(
        allowlist=["add", "notify"],
        max_input_bytes=1024,
        redact_fields={"token"},
    )

    @tool("add", input_model=AddIn, output_model=AddOut)
    def add(args: AddIn, ctx: ToolContext) -> AddOut:
        return AddOut(sum=args.a + args.b)

    @tool("notify", side_effect=True, idempotent=True)
    def notify(args: dict, ctx: ToolContext) -> str:
        return "notified"

    reg.register(add)
    reg.register(notify)
    return reg


async def main() -> None:
    store = InMemoryCheckpointStore()
    sink = SideEffectSink(store, run_id="demo-run", node_id="adder", node_version="1")
    registry = _build_registry()

    runtime = Runtime(
        run_id="demo-run",
        agent_name="adder",
        started_at=time.time(),
        logger=logging.getLogger("demo"),
    )

    # 1) basic validated tool call
    ctx = ToolContext(run_id=runtime.run_id, node_id="adder", side_effect_sink=sink)
    res = await registry.invoke("add", {"a": 2, "b": 3}, ctx)
    print("add ->", res.output)

    # 2) side-effect idempotency: same payload runs the effect only once
    await registry.invoke("notify", {"token": "secret", "id": 1}, ctx)
    await registry.invoke("notify", {"token": "secret", "id": 1}, ctx)
    print("side-effect effect invocations:", sink.write_count)

    # 3) middleware composition over the agent
    wrapped = MiddlewareAgent(
        Adder(registry, sink),
        [
            LoggingMiddleware(redact_fields={"token"}),
            RateLimitMiddleware(max_concurrent=4),
            RedactionMiddleware({"token"}),
        ],
    )
    state = await wrapped.run(AppState(total=0), runtime)
    print("agent result:", state)

    # 4) LLM request through the deterministic fake provider
    provider = FakeProvider()
    llm_resp = await provider.complete(
        LLMRequest(
            messages=[ChatMessage(role="user", content="summarize vuln X")],
            model="fake",
        ).with_tools([registry.get("add").spec])
    )
    print("llm response:", llm_resp.message.content)
    print("llm meta:", llm_resp.to_report_meta())


if __name__ == "__main__":
    asyncio.run(main())
