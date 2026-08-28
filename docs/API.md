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

### Current limits (phase 2)
No fan-out/fan-in, no loops, no EventBus, no retry/timeout/checkpoint, no LLM.
Those arrive in later phases.
