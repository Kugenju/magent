# magent public API

This document covers the stable public API shipped so far: phase 1 (agent /
state / result / runtime / sequential executor) and phase 2 (graph builder,
validation and conditional execution).

## Phase 1 — minimal kernel

### `BaseAgent`
```python
class BaseAgent(ABC):
    def __init__(self, name: str) -> None
    async def run(self, state: BaseModel, runtime: Runtime) -> AgentResult: ...
```
Subclass and implement `run`. The agent reads `state`, returns an `AgentResult`
proposing partial state updates; it must never mutate the framework-held state.

### `AgentResult`
```python
class AgentResult(BaseModel):
    status: ExecutionStatus            # SUCCESS | SKIPPED | FAILED
    updates: dict[str, Any]            # partial state update (validated on merge)
    message: str | None
    error: dict | None                 # structured error, not a raw exception
    metadata: dict[str, Any]
```

### `merge_updates(state, updates) -> StateT`
Returns a **new** state with `updates` applied. Unknown fields and type
mismatches raise `StateUpdateError`.

### `Runtime(run_id, agent_name, started_at, logger, clock=None)`
Read-only per-call context. `elapsed()` uses the injected `clock` (defaults to
`time.time`).

### `SequentialExecutor(agents, *, conflict_strategy="overwrite"|"reject", run_id=None, clock=None)`
- Runs agents in registration order, fail-fast.
- `run(initial_state) -> (final_state, ExecutionReport)`.
- Unique agent names enforced up front (`DuplicateAgentNameError`).
- A conflicting field update under `"reject"` fails the agent; under
  `"overwrite"` later writers replace earlier values.

### `ExecutionReport` / `StepRecord`
`run_id`, `initial_state`, `final_state`, `steps[]`, timings, `success`. Each
`StepRecord` has `order`, `agent_name`, optional `node_id`, `status`, timings,
`message`, `error`.

### Errors
`MagentError` (base) → `AgentError`, `StateUpdateError`, `DuplicateAgentNameError`.
All agent exceptions are normalized into `AgentError` in reports (original
type preserved under `error["cause"]`).

## Phase 2 — graph

### `END = "__end__"`
Sentinel target meaning "stop execution".

### `GraphBuilder`
```python
GraphBuilder()
    .add_node(node_id, agent)                 # register node (agent is BaseAgent)
    .set_entry_point(node_id)                 # exactly one entry
    .add_edge(source, target)                 # unconditional next node or END
    .add_conditional_edges(source, router, mapping)  # router(state)->label->target
    .compile(name=None) -> CompiledGraph      # validates, returns immutable graph
```
- A node may have **either** one unconditional edge **or** one set of
  conditional edges, not both.
- `compile()` runs validation; invalid topologies raise `GraphValidationError`.

### `CompiledGraph`
Immutable, validated topology. `nodes`, `edges`, `conditional`, `entry`, `name`.
`async run(initial_state, *, run_id=None, clock=None) -> (final_state, ExecutionReport)`.

### Validation (`GraphValidationError`)
Checks: non-empty node ids / unique; entry set & exists; edge source/target
exist or are `END`; conditional labels non-empty & unique with valid targets;
no mixed/duplicate out-edges; no cycles or self-references; all nodes reachable
from entry; every reachable path eventually reaches `END`.

### `GraphExecutor` semantics
- Walks one path from entry to `END`.
- Reuses phase-1 `merge_updates`, fail-fast and `AgentError` normalization.
- The router runs **after** the node's updates are merged, so it sees the
  latest state. `router` may be sync or async.
- Only the selected conditional branch executes; unselected branch targets are
  recorded as `NOT_EXECUTED` (visible in the report).
- Router exceptions / unknown labels are reported as `GraphRoutingError` and
  stop execution.

## Phase 3 — concurrency, fan-out/fan-in and EventBus

### `GraphBuilder` additions
```python
GraphBuilder()
    .add_parallel_edges(source, [t1, t2, ...])   # fan-out (explicit, keeps add_edge single-target)
    .add_join(node_id, [p1, p2, ...])            # fan-in; parents must be the incoming edges
```
- `add_parallel_edges` and `add_join` are additive on top of the phase-2 API;
  `add_edge(source, target)` still means a single unconditional successor.
- A node keeps at most one *outgoing* edge kind (normal / parallel / conditional).
- A join node's incoming edges must equal the parents declared in `add_join`.

### `CompiledGraph.run` additions
```python
async run(initial_state, *, run_id=None, clock=None,
          max_concurrency: int | None = None, event_bus=None)
```
`GraphExecutor` accepts the same `max_concurrency` / `event_bus` keyword args.

### Concurrency semantics
- Independent nodes run concurrently. `max_concurrency=None` (default) lets the
  topology run as wide as possible; `max_concurrency=N` bounds simultaneous agents
  via an `asyncio.Semaphore`, and the report records `peak_concurrency`.
- **Branch isolation:** each fan-out branch starts from the same snapshot taken
  at the parallel source. A branch can only submit updates via its
  `AgentResult`; it never sees another branch's intermediate state.
- **Fan-in merge:** at a join, the partial updates of all parents are merged over
  the source snapshot in a stable (declared) order. Different fields merge
  automatically; the same field updated by >1 branch raises
  `StateMergeConflictError` unless a reducer is registered.
- **Reducers:** declare `reducers: ClassVar[dict[str, Callable[[cur, new], new]]]`
  on the state model. A reducer must be deterministic and ideally associative
  (the merge order is the declared parent order, not completion order). Example:
  `reducers = {"trace": lambda cur, new: cur + new}`.
- **Failure lifecycle (fail-fast):** when a branch fails, sibling branches in the
  same fan-out are cancelled (`CANCELLED`), not-yet-started dependents are
  recorded `NOT_EXECUTED`, and no partial result of a cancelled branch is merged.
  `FAILED` / `CANCELLED` / `NOT_EXECUTED` are distinct and distinguishable.

### `ExecutionStatus` additions
`CANCELLED = "cancelled"` was added alongside `SUCCESS`, `SKIPPED`, `FAILED`,
`NOT_EXECUTED`.

### `ExecutionReport` / `StepRecord` additions
- `StepRecord.wait_ms: float` — time the node waited before it started running.
- `ExecutionReport.peak_concurrency: int` — highest number of agents running at
  once.
- `ExecutionReport.event_stats: dict | None` — `bus.stats()` snapshot when an
  EventBus was supplied.
- Each node produces **exactly one** final `StepRecord` (no duplicate records
  even when routing fails).

### EventBus
```python
from magent import EventBus, Event, EventHandlerError

bus = EventBus()                       # in-memory, at-most-once
sub = await bus.subscribe("agent.completed", handler)
await bus.publish(Event(topic="agent.completed", run_id=..., source=..., payload={...}))
sub.unsubscribe()
await bus.close()
```
- `Event`: `event_id`, `topic`, `run_id`, `source`, `created_at`, `payload`
  (structured, not a log string).
- Handlers may be sync or async. A handler exception is, by default, logged and
  the bus continues notifying other subscribers (`stats()["handler_errors"]`
  is incremented). With `EventBus(fail_on_handler_error=True)` it raises
  `EventHandlerError`.
- `publish`/`subscribe` after `close()` raise `EventHandlerError`.
- The EventBus is a side channel: it never participates in state merging or
  control flow, so it cannot corrupt graph state.

### Validation additions (`GraphValidationError`)
In addition to phase-2 rules: every parallel branch must reach a join; join
parents must match incoming edges; a join node cannot be a conditional target;
non-join nodes may have at most one predecessor (use `add_join` for fan-in).

### Current limits (phase 3)
No retry/timeout, no checkpoint/persistence, no distributed execution, no loops,
no dynamic planning, no LLM. Those arrive in later phases.
