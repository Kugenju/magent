"""Shortest copy-paste example: Agent -> State -> Result -> execution report.

Run with:
    python examples/quickstart.py
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from magent import AgentResult, BaseAgent, ExecutionStatus, SequentialExecutor


class CounterState(BaseModel):
    count: int = 0


class CountAgent(BaseAgent):
    async def run(self, state, runtime):
        runtime.logger.info("counting")
        return AgentResult(
            status=ExecutionStatus.SUCCESS,
            updates={"count": state.count + 1},
            message="incremented",
        )


async def main() -> None:
    executor = SequentialExecutor([CountAgent("counter")])
    final_state, report = await executor.run(CounterState())
    print("FINAL:", final_state.model_dump_json())
    print("REPORT:", report.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
