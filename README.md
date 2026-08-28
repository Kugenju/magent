# magent

A minimal, reusable, recoverable **multi-agent execution framework**, built in
phases. This repository currently contains **phase 1 + phase 2**: a deterministic
kernel (Agent/State/Result/Runtime, sequential executor) plus a validated,
conditionally-routed directed graph executor.

VulnTell (an open vulnerability-intelligence collection & source-quality
evaluation app) is planned as a downstream example that exercises this framework
— it lives under `examples/vulntell` in later phases and never pollutes the
`magent` core.

## Phase 1 scope

| In scope | Out of scope (later phases) |
|----------|------------------------------|
| `BaseAgent` protocol, typed `State`, `AgentResult`, `Runtime` | Directed Graph, conditional routing |
| `merge_updates` with validation | Concurrency, EventBus |
| `SequentialExecutor` (fail-fast) | Timeouts, retries, checkpoint/recovery |
| Structured `ExecutionReport` | LLM, tools, VulnTell business |

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

## Test

```bash
python -m pytest
```

All tests are offline (no network, no database).

## Roadmap

See `docs/DESIGN.md`, `docs/ROADMAP.md` and `docs/PHASE1.md`.
