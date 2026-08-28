# magent

A minimal, reusable, recoverable **multi-agent execution framework**, built in
phases. This repository currently contains **phase 1 + phase 2 + phase 3**: a
deterministic kernel (Agent/State/Result/Runtime, sequential executor), a
validated conditionally-routed directed graph executor, and concurrent
execution with fan-out/fan-in, branch-isolated state merging, a bounded
`asyncio` scheduler, and an in-process `EventBus`.

VulnTell (an open vulnerability-intelligence collection & source-quality
evaluation app) is planned as a downstream example that exercises this framework
— it lives under `examples/vulntell` in later phases and never pollutes the
`magent` core.

## Phase 1–3 scope

| In scope | Out of scope (later phases) |
|----------|------------------------------|
| `BaseAgent` protocol, typed `State`, `AgentResult`, `Runtime` | LLM, tools, VulnTell business |
| `merge_updates` with validation | Distributed execution |
| `SequentialExecutor` (fail-fast) | Checkpoint / recovery / persistence |
| Graph builder, validation, conditional routing | Loops, dynamic planning |
| Concurrent DAG: fan-out/fan-in, reducers, `EventBus` | Timeouts, retries, cancellation policies |

## Install

```bash
pip install -e ".[dev]"   # dev extras add pytest + pytest-asyncio
```

## Quick start (offline example)

```bash
python examples/producer_consumer.py
```

`ProducerAgent` writes a value, `ConsumerAgent` reads it — proving that one
agent's state update is visible to the next.

## Minimal usage

```python
import asyncio
from pydantic import BaseModel
from magent import BaseAgent, AgentResult, ExecutionStatus, SequentialExecutor

class State(BaseModel):
    count: int = 0

class Increment(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"count": state.count + 1})

async def main():
    state, report = await SequentialExecutor([Increment("inc")]).run(State())
    print(state.count, report.success)

asyncio.run(main())
```

## Public API

- `BaseAgent` — subclass and implement `async def run(state, runtime) -> AgentResult`.
- `AgentResult(status, updates, message, error, metadata)` — the only channel
  an agent uses to propose state changes.
- `merge_updates(state, updates)` — validate and apply a partial update,
  returning a **new** state instance.
- `Runtime(run_id, agent_name, started_at, logger)` — read-only per-call context.
- `SequentialExecutor(agents, conflict_strategy="overwrite"|"reject", run_id=None)`
  — runs agents in order, fail-fast, returns `(final_state, ExecutionReport)`.
- `ExecutionReport` / `StepRecord` — `run_id`, per-step status, timings, failure.

The executor enforces: unique agent names, unknown/typed-mismatched updates are
rejected, a failure stops subsequent agents (marked `NOT_EXECUTED`), and there is
**no implicit retry** in this phase.

## Graph execution (phase 2)

```python
import asyncio
from pydantic import BaseModel
from magent import BaseAgent, AgentResult, ExecutionStatus, GraphBuilder, END


class State(BaseModel):
    score: int = 0
    approved: bool = False


class Review(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"approved": state.score >= 10})


def route(state):
    return "approved" if state.approved else "rejected"


async def main():
    graph = (
        GraphBuilder()
        .add_node("review", Review("review"))
        .set_entry_point("review")
        .add_conditional_edges("review", route, {"approved": END, "rejected": END})
        .compile()
    )
    state, report = await graph.run(State(score=20))
    print(state.approved, report.success)


asyncio.run(main())
```

`compile()` validates the topology first (invalid graphs raise
`GraphValidationError`); the executor walks one path to `END`. See
`docs/API.md` for the full phase-2 API and current limits.

## Concurrent execution (phase 3)

```python
import asyncio
from typing import ClassVar
from pydantic import BaseModel
from magent import BaseAgent, AgentResult, GraphBuilder, END, EventBus


class State(BaseModel):
    trace: list[str] = []
    reducers: ClassVar[dict] = {"trace": lambda cur, new: cur + new}


class Step(BaseAgent):
    def __init__(self, name, tag):
        super().__init__(name)
        self.tag = tag

    async def run(self, state, runtime):
        return AgentResult(updates={"trace": [self.tag]})


async def main():
    bus = EventBus()
    graph = (
        GraphBuilder()
        .add_node("a", Step("a", "A"))
        .add_node("b", Step("b", "B"))
        .add_node("c", Step("c", "C"))
        .add_node("d", Step("d", "D"))
        .set_entry_point("a")
        .add_parallel_edges("a", ["b", "c"])   # fan-out
        .add_edge("b", "d")
        .add_edge("c", "d")
        .add_join("d", ["b", "c"])             # fan-in (reducer merges "trace")
        .add_edge("d", END)
        .compile()
    )
    state, report = await graph.run(State(), max_concurrency=4, event_bus=bus)
    print(sorted(state.trace))          # ['A', 'B', 'C', 'D']
    print(report.peak_concurrency)      # 2 (a, then b+c, then d)
    print(report.event_stats)           # delivery counts from the bus


asyncio.run(main())
```

Fan-out branches each start from the same snapshot and only submit updates via
`AgentResult`. At a join the parents' updates are merged in declared order;
fields updated by more than one branch require a reducer on the state model or
raise `StateMergeConflictError`. A branch failure cancels its siblings
(`CANCELLED`), leaves unstarted dependents `NOT_EXECUTED`, and never merges a
cancelled branch's partial result. The `EventBus` is a side channel and never
touches graph state.

## Test

```bash
python -m pytest
```

All tests are offline (no network, no database).

## Roadmap

See `docs/DESIGN.md`, `docs/ROADMAP.md` and `docs/PHASE1.md`.
