from __future__ import annotations

import pytest

from magent import AgentResult, BaseAgent, ExecutionStatus


def test_base_agent_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseAgent("x")  # type: ignore[abstract]


class DummyAgent(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult()


def test_concrete_agent_exposes_name():
    agent = DummyAgent("alpha")
    assert agent.name == "alpha"
