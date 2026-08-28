"""Offline Producer/Consumer demo for the magent phase-1 kernel.

Run with:
    python examples/producer_consumer.py
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from magent import AgentResult, BaseAgent, ExecutionStatus, SequentialExecutor


class DemoState(BaseModel):
    value: int = 0
    messages: list[str] = Field(default_factory=list)


class ProducerAgent(BaseAgent):
    async def run(self, state, runtime):
        runtime.logger.info("producer running")
        return AgentResult(
            status=ExecutionStatus.SUCCESS,
            updates={"value": state.value + 1, "messages": state.messages + ["produced"]},
            message="incremented value",
        )


class ConsumerAgent(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(
            status=ExecutionStatus.SUCCESS,
            updates={"messages": state.messages + [f"consumed:{state.value}"]},
            message="appended confirmation",
        )


async def main() -> None:
    executor = SequentialExecutor([ProducerAgent("producer"), ConsumerAgent("consumer")])
    final_state, report = await executor.run(DemoState())
    print("FINAL STATE:", final_state.model_dump_json(indent=2))
    print("REPORT:", report.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
