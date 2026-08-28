"""Phase 5 interruption / resume demo.

Run a 3-step sequential workflow, persist every commit boundary to SQLite, then
*simulate a crash* (drop the checkpoints that were flushed after the first
committed node) and resume the same ``run_id``. The resumed run replays only the
uncommitted tail and reproduces the exact final state of an uninterrupted run.

Usage:

    python examples/checkpoint_resume.py

It prints the fresh report, the simulated-crash report and the resumed report so
you can see ``replayed_nodes`` / ``abandoned_attempts`` in action.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3

from pydantic import BaseModel

from magent import AgentResult, BaseAgent, SequentialExecutor
from magent.checkpoint import SqliteCheckpointStore


class DemoState(BaseModel):
    value: int = 0
    visited: list[str] = []


class Step(BaseAgent):
    def __init__(self, name, by=1):
        super().__init__(name)
        self.by = by

    async def run(self, state, runtime):
        # A tiny sleep so the run is realistic; not required for correctness.
        await asyncio.sleep(0.01)
        return AgentResult(
            updates={
                "value": state.value + self.by,
                "visited": state.visited + [runtime.agent_name],
            }
        )


DB_PATH = "checkpoint_demo.db"
RUN_ID = "demo-run-1"


async def main() -> None:
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    agents = [Step("a"), Step("b"), Step("c")]

    # 1) Fresh, uninterrupted run (persisted).
    store = SqliteCheckpointStore(DB_PATH)
    ex = SequentialExecutor(agents, checkpoint_store=store, run_id=RUN_ID)
    full_state, full_report = await ex.run(DemoState())
    print("== uninterrupted run ==")
    print("  final:", full_state.model_dump())
    print("  success:", full_report.success, "steps:", [s.node_id for s in full_report.steps])

    # 2) Simulate a crash: the process died after only the first node committed.
    #    We drop the checkpoints that were flushed afterwards from the store.
    await store.close()
    conn = sqlite3.connect(DB_PATH)
    # Keep only: RUN_STARTED (0), a NODE_STARTED (1), a NODE_COMMITTED (2).
    conn.execute("DELETE FROM checkpoints WHERE checkpoint_seq >= 3")
    conn.commit()
    conn.close()
    print("\n== simulated crash: only node 'a' was durably committed ==")

    # 3) Resume the exact same run_id.
    store2 = SqliteCheckpointStore(DB_PATH)
    ex2 = SequentialExecutor(agents, checkpoint_store=store2, run_id=RUN_ID)
    resumed_state, resumed_report = await ex2.resume(RUN_ID, DemoState())
    await store2.close()

    print("\n== resumed run ==")
    print("  final:", resumed_state.model_dump())
    print("  resumed:", resumed_report.resumed)
    print("  replayed_nodes:", resumed_report.replayed_nodes)
    print("  abandoned_attempts:", resumed_report.abandoned_attempts)
    print("  resumed_from_seq:", resumed_report.resumed_from_seq)

    assert resumed_state.model_dump() == full_state.model_dump(), "resume must match the uninterrupted result"
    assert "a" not in resumed_report.replayed_nodes
    assert set(resumed_report.replayed_nodes) == {"b", "c"}
    print("\nOK: resume reproduced the uninterrupted final state.")


if __name__ == "__main__":
    asyncio.run(main())
