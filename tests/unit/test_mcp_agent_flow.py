"""Phase 10 — end-to-end flow: agent -> ToolRegistry -> McpToolProxy -> fake server.

Covers the A-plan acceptance items that need a *node* context:
- a regular agent reads MCP tool results into state (through the phase-1
  executor contract, unchanged),
- a raised retryable MCP error (rate limit) is retried by ``ReliabilityPolicy``
  exactly like a local tool failure.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from magent import (
    AgentResult,
    BaseAgent,
    ExecutionStatus,
    ReliabilityPolicy,
    RetryPolicy,
    Runtime,
    SequentialExecutor,
)
from magent.mcp.fake import (
    FakeMcpServer,
    FakeToolDefinition,
    FakeTransportFactory,
    fake_outcome,
)
from magent.mcp.loader import McpToolLoader
from magent.mcp.errors import build_tool_error
from magent.mcp.spec import McpServerConfig
from magent.tools.context import ToolContext
from magent.tools.registry import ToolRegistry

class FlowState(BaseModel):
    prompt: str = "hello"
    reply: str = ""


def _success_server():
    return FakeMcpServer(
        "backend",
        [
            FakeToolDefinition(
                name="echo",
                description="echo tool",
                input_schema={
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                    "required": ["msg"],
                },
                read_only=True,
                handler=lambda args: fake_outcome(text=f"echo:{args.get('msg', '')}"),
            )
        ],
    )


def _flaky_server(calls_needed=3):
    counter = {"n": 0}

    def handler(args):
        counter["n"] += 1
        if counter["n"] < calls_needed:
            raise build_tool_error(
                "rate_limited", "mcp:backend__echo", "r1", "429 slow down"
            )
        return fake_outcome(text="ok")

    return FakeMcpServer(
        "backend",
        [
            FakeToolDefinition(
                name="echo",
                description="echo tool",
                input_schema={
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                    "required": ["msg"],
                },
                read_only=True,
                handler=handler,
            )
        ],
    ), counter


class McpEchoAgent(BaseAgent):
    """Reads the backend echo tool result into state via the registry."""

    def __init__(self, name: str, registry: ToolRegistry, tool_name: str) -> None:
        super().__init__(name)
        self._registry = registry
        self._tool = tool_name

    async def run(self, state: BaseModel, runtime: Runtime) -> AgentResult:
        if not isinstance(state, FlowState):
            raise TypeError("expected FlowState")
        ctx = ToolContext(run_id=runtime.run_id, node_id=self.name)
        res = await self._registry.invoke(self._tool, {"msg": state.prompt}, ctx)
        # A non-ok tool failure is the agent's decision surface; a *raised*
        # retryable MCP error would propagate and hit the retry policy.
        if not res.ok:
            return AgentResult(status=ExecutionStatus.FAILED, error=res.error)
        return AgentResult(updates={"reply": str(res.output)})


async def test_agent_consumes_mcp_tool_result():
    server = _success_server()
    registry = ToolRegistry()
    loader = McpToolLoader(
        registry, [McpServerConfig("backend", FakeTransportFactory(server), allow_tools=("echo",))]
    )
    await loader.load()
    try:
        agent = McpEchoAgent("echo-agent", registry, "backend__echo")
        state, report = await SequentialExecutor([agent]).run(FlowState())
        assert state.reply == "echo:hello"
        assert report.success is True
        assert len(server.call_log) == 1
    finally:
        await loader.close()


async def test_retryable_mcp_error_retried_by_reliability_policy():
    server, counter = _flaky_server(calls_needed=3)
    registry = ToolRegistry()
    loader = McpToolLoader(
        registry, [McpServerConfig("backend", FakeTransportFactory(server), allow_tools=("echo",))]
    )
    await loader.load()
    try:
        agent = McpEchoAgent("echo-agent", registry, "backend__echo")
        policy = ReliabilityPolicy(
            retry=RetryPolicy(max_attempts=5, backoff_base=0.01, backoff_max=0.05)
        )
        state, report = await SequentialExecutor([agent], reliability=policy).run(FlowState())
        assert state.reply == "ok"
        assert report.retry_count == 2
        assert counter["n"] == 3
        assert len(server.call_log) == 3
    finally:
        await loader.close()


async def test_non_retryable_mcp_error_fails_the_node():
    server = _success_server()
    registry = ToolRegistry()
    loader = McpToolLoader(
        registry, [McpServerConfig("backend", FakeTransportFactory(server), allow_tools=("echo",))]
    )
    await loader.load()
    try:
        broken = FakeToolDefinition(
            name="breaks",
            read_only=True,
            handler=lambda args: (_ for _ in ()).throw(
                build_tool_error("permanent", "mcp:backend__breaks", "r1", "kaput")
            ),
        )
        server._tools["breaks"] = broken  # test-only injection into telemetry holder
        agent = McpEchoAgent("echo-agent", registry, "backend__breaks")
        _, report = await SequentialExecutor([agent]).run(FlowState())
        assert report.success is False
    finally:
        await loader.close()


async def test_unknown_registry_name_rejected_at_invoke():
    registry = ToolRegistry()
    ctx = ToolContext(run_id="r1", node_id="n1")
    with pytest.raises(Exception):
        await registry.invoke("missing__tool", {}, ctx)
