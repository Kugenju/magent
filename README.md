# magent

A minimal, reusable, recoverable **multi-agent execution framework**, built in
phases. This repository currently contains **phase 1 + phase 2 + phase 3 +
phase 4 + phase 5 + phase 6 + phase 7 + phase 8**: a deterministic kernel (Agent/State/Result/Runtime,
sequential executor), a validated conditionally-routed directed graph executor,
concurrent execution with fan-out/fan-in, branch-isolated state merging, a
bounded `asyncio` scheduler, an in-process `EventBus`, configurable node
**timeout / retry / cancellation / error classification**, opt-in
**checkpointing, crash recovery and idempotent side effects**, a unified
**tool protocol**, pluggable **LLM provider** abstraction and composable
**middleware** extension layer, and (phase 8) an **offline evaluation & observability**
suite: a read-only `Trace`/`Span`/`RunSummary` observability protocol, an offline
`benchmarks/` runner (determinism / security / parallel reliability / checkpoint
recovery), VulnTell source-quality evaluation, and a reference-framework comparison
recorder that records versions without emitting rankings.

VulnTell (an open vulnerability-intelligence collection & source-quality
evaluation app) is implemented as a downstream application that exercises this
framework. Its current implementation lives under `apps/vulntell`; the
`examples/vulntell` package remains as a compatibility entry point and never
pollutes the `magent` core.

VulnTell 当前产品化状态、阶段完成汇总以及情报源采集/批次交付方法，见
[`docs/vulntell/PHASE_COMPLETION_SUMMARY.md`](docs/vulntell/PHASE_COMPLETION_SUMMARY.md)、
[`docs/vulntell/INTELLIGENCE_COLLECTION_GUIDE.md`](docs/vulntell/INTELLIGENCE_COLLECTION_GUIDE.md)
和 [`docs/NEXT_STAGE.md`](docs/NEXT_STAGE.md)。

## Current scope (phases 1–8; phase 9 release hardening)

> Phase 9 hardens the project for public release: documentation consistency, a framework
> comparison (`docs/architecture/COMPARISON.md`), license/third-party notices, CI quality gates, clean-install
> verification and a release checklist. It does **not** change execution semantics. See
> [`docs/phases/PHASE9.md`](docs/phases/PHASE9.md).

| In scope | Out of scope (later phases) |
|----------|------------------------------|
| `BaseAgent` protocol, typed `State`, `AgentResult`, `Runtime` | Distributed execution |
| `merge_updates` with validation | Distributed execution |
| `SequentialExecutor` (fail-fast) | Distributed execution |
| Graph builder, validation, conditional routing | Loops, dynamic planning |
| Concurrent DAG: fan-out/fan-in, reducers, `EventBus` | Distributed execution |
| Reliability: node timeout, bounded retry, caller cancellation, error strategy | Distributed execution |
| Opt-in SQLite checkpoint, recovery and idempotency | VulnTell business |
| Tools: schema-validated sync/async, allowlist, timeout, size-limit | Distributed execution |
| LLM: pluggable provider, deterministic `FakeProvider`, optional OpenAI adapter | VulnTell business |
| Middleware: logging / rate-limit / size-limit / redaction, deterministic compose | Distributed execution |
| VulnTell offline vertical example | Production web dashboard |
| Observability: read-only `Trace`/`Span`/`RunSummary` + redaction | Live tracing backend |
| Offline benchmarks: determinism / security / parallel reliability / recovery | Distributed benchmark |
| VulnTell source-quality evaluation + reference comparison recorder | External ranking |

阶段 8 的评测、统一 trace、benchmark 和参考框架对比已实现并随仓库提交；详见
[`docs/phases/PHASE8.md`](docs/phases/PHASE8.md) 与
[`benchmarks/README.md`](benchmarks/README.md)。

## Install

```bash
pip install -e ".[dev]"   # dev extras add pytest + pytest-asyncio + mypy
```

The install is **offline-first**: it needs only `pydantic` at runtime and no API key, network access, or
external service. `import magent` and the version string (`import importlib.metadata; version("magent")`)
work after install.

### Packaging scope

- The published package contains only the framework core under `src/magent`.
- `examples/` and `benchmarks/` are **repository assets** run from a source checkout; they are intentionally
  **not** bundled into the wheel/sdist (setuptools `packages.find` is scoped to `src`). Install from the
  cloned repository to run the examples and the benchmark CLI.

## Quick start (offline example)

```bash
python examples/quickstart.py             # shortest: Agent -> State -> Result -> report
python examples/producer_consumer.py      # phase 1: state visibility across agents
python examples/checkpoint_resume.py      # phase 5: crash → resume → identical result
python examples/phase6_tools_llm_middleware.py   # phase 6: tools + LLM + middleware
python -m apps.vulntell                   # VulnTell application (offline)
python -m apps.vulntell --json            # machine-readable report
python -m apps.vulntell --trace benchmarks/out/vulntell   # emit trace + summary
python -m benchmarks.cli --out benchmarks/out   # phase 8: offline evaluation suite
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
**no implicit retry** unless a `ReliabilityPolicy` is configured.

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
`docs/architecture/API.md` for the full phase-2 API and current limits.

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

## Reliability (phase 4)

```python
import asyncio
from pydantic import BaseModel
from magent import (
    BaseAgent, AgentResult, SequentialExecutor,
    ReliabilityPolicy, RetryPolicy, TimeoutPolicy, RetryableError,
)

class State(BaseModel):
    count: int = 0

class Flaky(BaseAgent):
    def __init__(self, name):
        super().__init__(name)
        self.calls = 0
    async def run(self, state, runtime):
        self.calls += 1
        if self.calls < 3:
            raise RetryableError("transient")
        return AgentResult(updates={"count": state.count + 1})

async def main():
    policy = ReliabilityPolicy(
        retry=RetryPolicy(max_attempts=5, backoff_base=0.1, backoff_max=2.0),
        timeout=TimeoutPolicy(node_timeout=10.0),
    )
    state, report = await SequentialExecutor(
        [Flaky("flaky")], reliability=policy
    ).run(State())
    print(state.count, report.retry_count)   # 1, 2

asyncio.run(main())
```

`ReliabilityPolicy()` (no args) preserves the phase 1–3 behaviour: no retry, no
timeout, fail-fast. Timeouts are reported as `status = FAILED` with
`terminal_reason = "timeout"`. Cancelling the run task marks in-flight nodes
`CANCELLED` and never-started nodes `NOT_EXECUTED` (`cancellation_reason = "caller"`),
without triggering a retry. Both executors emit attempt lifecycle events on the
`EventBus` (`agent.attempt.started`, `agent.attempt.succeeded`, `agent.attempt.failed`,
`agent.attempt.timeout`, `agent.retry`).

## Checkpoint & recovery (phase 5)

```bash
python examples/checkpoint_resume.py
```

Pass an opt-in `CheckpointStore` to either executor. Every node writes a
`NODE_STARTED` snapshot before it runs and a `NODE_COMMITTED` record after its
state is merged, so a crashed run can be continued from the last committed
boundary:

```python
import asyncio
from pydantic import BaseModel
from magent import BaseAgent, AgentResult, SequentialExecutor, SqliteCheckpointStore

class State(BaseModel):
    value: int = 0

class Step(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"value": state.value + 1})

async def main():
    store = SqliteCheckpointStore("run.db")
    ex = SequentialExecutor([Step("a"), Step("b")], checkpoint_store=store, run_id="r1")
    state, report = await ex.run(State())
    # ... process dies after 'a' committed ...
    ex2 = SequentialExecutor([Step("a"), Step("b")], checkpoint_store=store, run_id="r1")
    state, report = await ex2.resume("r1", State())   # replays only 'b'
    print(report.resumed, report.replayed_nodes)        # True, ['b']
```

`GraphExecutor` supports the same `checkpoint_store` + `resume` API, including
fan-out/fan-in and conditional routes. External side effects can be made
idempotent with `SideEffectSink` + `execution_key` (the key is stable across
retries and recovery replays, so the effect runs at most once).

## Tools, LLM & middleware (phase 6)

Tools are the only sanctioned way for an agent to perform a side effect or a
structured computation. The registry enforces an allowlist, input/output schema
validation, a size limit, a concurrency limiter and a per-call timeout, and
funnels idempotent side-effect tools through `SideEffectSink`:

```python
from pydantic import BaseModel
from magent import ToolRegistry, ToolContext, tool

class AddIn(BaseModel):
    a: int
    b: int
class AddOut(BaseModel):
    sum: int

reg = ToolRegistry(allowlist=["add"])
@tool("add", input_model=AddIn, output_model=AddOut)
def add(args: AddIn, ctx: ToolContext) -> AddOut:
    return AddOut(sum=args.a + args.b)
reg.register(add)
```

The core depends only on the abstract `LLMProvider` protocol and the
deterministic `FakeProvider`, so it runs with **no API key and no network**.
Vendor SDKs (e.g. OpenAI) are loaded lazily via `get_llm_provider("openai", ...)`:

```python
from magent import FakeProvider, LLMRequest, ChatMessage
provider = FakeProvider()
resp = await provider.complete(LLMRequest(messages=[ChatMessage(role="user", content="hi")]))
```

Middleware wraps an agent call (never the executor's scheduling/retry/checkpoint
logic). `before` runs in order, `after` in reverse, and an exception propagates
unchanged unless a middleware explicitly converts it in `on_error`:

```python
from magent import MiddlewareAgent, LoggingMiddleware, RateLimitMiddleware, RedactionMiddleware
agent = MiddlewareAgent(inner, [LoggingMiddleware(), RateLimitMiddleware(4), RedactionMiddleware({"token"})])
```

## Test

```bash
python -m pytest
```

All tests are offline (no network, external services, or production database).

## Roadmap

The VulnTell vertical example (phase 7) is implemented and committed under
`apps/vulntell`; `examples/vulntell` remains a compatibility entry point. Phase 8 (observability + offline evaluation) is implemented
and committed under `src/magent/observability` and `benchmarks/`. See
`docs/architecture/DESIGN.md`, `docs/phases/ROADMAP.md`, `docs/phases/PHASE6.md`, `docs/phases/PHASE7.md` and
`docs/phases/PHASE8.md` and `docs/phases/PHASE9.md` for the current boundaries and acceptance criteria.

Phase 7 and phase 8 are implemented and committed. Phase 9 (release,
documentation, CI and presentation) is the current development stage. The `magent` core remains
usable offline without any LLM SDK or network access. VulnTell runs fully offline
(fixture sources, deterministic metrics) and uses the optional `FakeProvider`
only for non-binding textual explanation. Phase 8 adds a read-only observability
protocol (`Trace`/`Span`/`RunSummary`) integrated with the VulnTell CLI via
`--trace`, plus an offline `benchmarks/` suite that measures determinism,
isolation/security (no accidental side effects), parallel reliability (retry /
timeout) and checkpoint recovery, and a reference-framework comparison recorder
that records versions without emitting rankings.

## Release & license

- `CHANGELOG.md` — version history and the `0.x` compatibility policy.
- `docs/architecture/COMPARISON.md` — design comparison with LangGraph / AutoGen / CrewAI (not ranked).
- `docs/evaluation/BENCHMARKS.md` — phase-8 evaluation results and reproduction.
- `RELEASE_CHECKLIST.md` — pre-release verification checklist.
- `LICENSE` (MIT) and `THIRD_PARTY_NOTICES.md` — license, dependencies, fixture provenance and safe-use.

The project is released as a GitHub source repository. PyPI publishing and a production Web dashboard are
explicitly out of scope for this release and require separate acceptance.
