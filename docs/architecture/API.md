# magent public API

This document covers the stable public API shipped so far: phases 1–8
(agent/state/result/runtime, graph execution, concurrency/EventBus,
timeout/retry/cancellation reliability, opt-in checkpoint/recovery, the
tool / LLM-provider / middleware extension layer, the VulnTell example, and
the read-only observability/evaluation layer).

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

## Phase 4 — reliability (timeout / retry / cancellation / error strategy)

Phase 4 adds configurable node timeout, bounded exponential-backoff retry, caller
cancellation, and a retryable/non-retryable error classification. A single shared
`run_node` runner implements all of this so `SequentialExecutor` and
`GraphExecutor` never diverge. **Without configuration, behaviour is identical to
phase 1–3** (`ReliabilityPolicy()` = `max_attempts=1`, no timeout, fail-fast).

### `ReliabilityPolicy`
```python
ReliabilityPolicy(
    retry: RetryPolicy | None = None,     # defaults to RetryPolicy() (no retry)
    timeout: TimeoutPolicy | None = None,  # defaults to TimeoutPolicy() (no timeout)
    on_failure: str = "fail_fast",        # only "fail_fast" in phase 4
)
```
Policies are **immutable** after construction.

### `RetryPolicy`
```python
RetryPolicy(
    max_attempts: int = 1,          # total executions (initial call + retries)
    backoff_base: float = 0.5,      # base delay (seconds)
    backoff_max: float = 30.0,      # cap on the exponential delay
    jitter: float = 0.1,            # [0, 1] fraction added as jitter*rng()
    retryable_exceptions: tuple = (),  # extra exception types treated as retryable
)
```
- `should_retry(attempt)` → `attempt < max_attempts`.
- `backoff_delay(attempt, rng)` → `min(backoff_max, backoff_base * 2**(attempt-1)) + jitter*rng()`.
- Validation: `max_attempts >= 1`, `backoff_base >= 0`, `backoff_max >= backoff_base`, `0 <= jitter <= 1`.

### `TimeoutPolicy`
```python
TimeoutPolicy(node_timeout: float | None = None)   # seconds; None = no timeout
```

### Error classification (`magent.reliability.errors`)
- `RetryableError` — agents raise/annotate to mark a transient failure. `TemporaryError` is a
  convenience subclass.
- `NonRetryableError` — explicitly fatal.
- `classify_exception(exc, retryable_exceptions)` — `RetryableError` and any
  `retryable_exceptions` are retryable; `StateUpdateError`, `StateMergeConflictError`,
  `GraphValidationError`, `NonRetryableError` (and `CancelledError`) are **not**;
  anything else is non-retryable by default.
- `classify_result(result)` — a returned `AgentResult` with `error["retryable"] is True`
  is retried.

### `run_node(agent, state, runtime, *, policy, sleeper=asyncio.sleep, rng=random.random, clock=time.time, emit=None, attempts_log=None)`
Runs a single node with the policy applied (timeout via `asyncio.wait_for`, retry
loop, attempt events). Returns a `NodeRunOutcome(status, result, attempts, terminal_reason, error)`.
It **never merges state** — only a successful attempt's `updates` are merged by the executor.

### `ExecutionStatus` / `AttemptRecord` / report additions
- `AttemptRecord`: `attempt`, `started_at`, `finished_at`, `duration_ms`, `status`, `error`.
- `StepRecord.attempts: list[AttemptRecord]` and `StepRecord.terminal_reason`:
  `success | skipped | failed | timeout | cancelled`.
- `ExecutionReport.cancellation_reason: str | None` (`"caller"` on caller cancel),
  `retry_count: int`, `timeout_count: int`.
- A timeout is reported as `status = FAILED` with `terminal_reason = "timeout"` and an
  `error["type"] == "NodeTimeoutError"` attempt record — `TIMEOUT` is intentionally **not**
  a separate `ExecutionStatus` (per spec).

### Executor wiring
```python
SequentialExecutor(agents, *, reliability=None, sleeper=None, rng=None, event_bus=None)
CompiledGraph.run(initial_state, *, reliability=None, sleeper=None, rng=None, event_bus=None)
```
- `sleeper` / `rng` are injectable for deterministic tests (e.g. `sleeper=lambda _: asyncio.sleep(0)`).
- `event_bus` receives attempt lifecycle events: `agent.attempt.started`,
  `agent.attempt.succeeded`, `agent.attempt.failed`, `agent.attempt.timeout`, `agent.retry`.
- **Caller cancellation:** cancelling the run task marks in-flight nodes `CANCELLED`,
  never-started nodes `NOT_EXECUTED`, and sets `cancellation_reason = "caller"`. Caller
  cancellation does **not** trigger a retry.

### Current limits (phase 4)
No `skip_dependents` / `continue` on_failure strategies yet (only `fail_fast`);
no distributed execution. Checkpoint and persistence are described in phase 5.

## Phase 5 — checkpoint, recovery & idempotency

Phase 5 adds an **opt-in** `CheckpointStore` and an explicit `resume` operation
to both executors. Without a `checkpoint_store` the executors behave exactly as
in phases 1–4 (no I/O, no overhead). With a store, every node writes a
`NODE_STARTED` snapshot before it runs and a `NODE_COMMITTED` record after it
successfully merges its state; a crashed run can be continued from the last
committed boundary.

### `CheckpointStore` (protocol)
```python
class CheckpointStore(Protocol):
    async def create_run(self, run: RunRecord) -> None
    async def append(self, cp: CheckpointRecord) -> None          # idempotent; conflict => CheckpointConflictError
    async def latest(self, run_id: str) -> CheckpointRecord | None
    async def list_checkpoints(self, run_id: str) -> list[CheckpointRecord]  # ordered by seq
    async def load_run(self, run_id: str) -> RunRecord
    async def record_effect(self, rec: EffectRecord) -> bool       # True if newly recorded
    async def get_effect(self, execution_key: str) -> EffectRecord | None
    async def close(self) -> None
```

### Concrete stores
- `InMemoryCheckpointStore()` — test / single-process default.
- `SqliteCheckpointStore(path=":memory:")` — single-writer file store; all SQL
  runs off the event loop via `run_in_executor`, WAL, transactional appends.

### Record models (`magent.checkpoint.models`)
- `CheckpointPhase` — `RUN_STARTED | NODE_STARTED | NODE_COMMITTED |
  RUN_COMPLETED | RUN_FAILED | RUN_CANCELLED`.
- `RunRecord(run_id, workflow_id, workflow_version, state_type, state_schema_hash,
  initial_state, status, created_at, updated_at)`.
- `CheckpointRecord(run_id, workflow_id, workflow_version, state_type,
  state_schema_hash, checkpoint_seq, phase, node_id, node_version,
  input_state, output_state, updates, route, activated_nodes, frontier,
  attempts, created_at, checksum)` — `checksum` is auto-computed and stable.
- `EffectRecord(execution_key, run_id, node_id, node_version, status, result_json, created_at)`.

### `SequentialExecutor` additions
```python
SequentialExecutor(
    agents, *,
    checkpoint_store=None,
    workflow_id="sequential",
    workflow_version="1",
)
final_state, report = await ex.run(initial_state)
final_state, report = await ex.resume(run_id, initial_state)   # requires a store
```
- `checkpoint_seq` is a monotonic integer within a run; `(run_id, checkpoint_seq)`
  is the unique durability key.
- `resume` replays only the uncommitted tail; already-committed nodes are
  reconstructed as `SUCCESS` `StepRecord`s with no re-execution.

### `GraphExecutor` additions
```python
GraphExecutor(
    graph, *,
    checkpoint_store=None,
    workflow_id="graph",
    workflow_version="1",
)
final_state, report = await ex.run(initial_state)
final_state, report = await ex.resume(run_id, initial_state)
```
- On resume the committed frontier (node outputs, updates, conditional routes,
  activated branches) is prefilled; fan-out/fan-in continue transparently.
- `NODE_COMMITTED` for a conditional node carries `activated_nodes` so the chosen
  branch resumes correctly.

### `ExecutionReport` additions (phase 5)
- `resumed: bool` — whether this run was a `resume`.
- `resumed_from_seq: int | None` — the highest checkpoint seq before resume.
- `abandoned_attempts: int` — `NODE_STARTED` records with no matching
  `NODE_COMMITTED` (crashed attempts) at resume time.
- `replayed_nodes: list[str]` — nodes actually (re-)executed during a resume.

### Idempotency (`magent.checkpoint.idempotency`)
```python
from magent import SideEffectSink, execution_key

sink = SideEffectSink(store, run_id=..., node_id=..., node_version="1", clock=...)
result = await sink.write(input_state, "send_email", payload, send_email_fn)
```
- `execution_key(run_id, node_id, node_version, input_state, op)` is **stable
  across retries and recovery replays** (it deliberately excludes `attempt`).
- `SideEffectSink.write` invokes `effect_fn` at most once per key; on replay it
  returns the previously recorded `result_json` instead of re-invoking the
  side effect. `sink.write_count` counts real invocations.

### Errors (`magent.checkpoint.errors`)
`CheckpointError` → `CheckpointCompatibilityError` (run/state/version mismatch on
resume, carries `field`/`expected`/`actual`) and `CheckpointConflictError`
(same `(run_id, checkpoint_seq)` submitted with different content).

### Current limits (phase 5)
No distributed checkpoint, no leader election, no cross-DB distributed
transaction, no pickle, no automatic schema migration; cyclic graphs remain out
of scope. (Tools/LLM/middleware shipped in phase 6 — see below.)

## Phase 6 — tools, LLM and middleware

### Tools (`magent.tools`)
```python
from magent import ToolRegistry, ToolContext, FunctionTool, ToolResult, ToolSpec, tool

# Declarative decorator: schema-validated, sync or async.
@tool("add", input_model=AddIn, output_model=AddOut)
def add(args: AddIn, ctx: ToolContext) -> AddOut:
    return AddOut(sum=args.a + args.b)

reg = ToolRegistry(
    allowlist=["add"],            # unknown/unlisted -> ToolPermissionError
    max_input_bytes=4096,         # oversize input -> ToolValidationError
    limiter=ConcurrencyLimiter(8),# caps concurrent invocations
    redact_fields={"token"},     # observability redaction
)
reg.register(add)
result: ToolResult = await reg.invoke("add", {"a": 1, "b": 2}, ctx)
```
- `ToolSpec` — immutable identity (`name`, `version`, `description`,
  `input_model`, `output_model`, `side_effect`, `idempotent`). Exported via
  `to_metadata()` (safe, no executable objects).
- `FunctionTool.invoke` runs sync functions via `asyncio.to_thread` and async
  functions directly; an optional `timeout` raises `ToolTimeoutError`.
- `ToolRegistry.invoke` enforces: registration uniqueness, allowlist,
  input/output pydantic validation (100%), input size limit, a concurrency
  limiter, and a per-call timeout. Idempotent side-effect tools are funnelled
  through `context.side_effect_sink` so the effect runs at most once.
- Errors: `ToolError` → `ToolPermissionError` (not registered / not allowed /
  side-effect without `idempotent=True`), `ToolValidationError` (schema/size),
  `ToolTimeoutError`.

### LLM (`magent.llm`)
```python
from magent import LLMProvider, FakeProvider, get_llm_provider, LLMRequest, LLMResponse, ChatMessage

provider = FakeProvider()                      # deterministic, offline, no SDK
resp: LLMResponse = await provider.complete(
    LLMRequest(messages=[ChatMessage(role="user", content="hi")]).with_tools([spec])
)
provider = get_llm_provider("openai", api_key="...", model="gpt-4o-mini")  # lazy import
```
- `LLMProvider` is a runtime-checkable `Protocol` with `async complete(request, context)`.
- `LLMRequest` / `LLMResponse` / `ChatMessage` / `Usage` are pure pydantic models;
  `tools` carries only safe tool metadata, `response_schema` is a pydantic class
  for output validation and is not serialized.
- `FakeProvider` supports scripted `responses`, a `handler` callable, or an echo
  mode — sufficient for offline tests and the deterministic core.
- `get_llm_provider("openai", ...)` imports the OpenAI SDK lazily; the core never
  depends on it. Provider errors map to `LLMError` → `LLMRateLimitError` /
  `LLMAuthError` / `LLMInvalidParamError` / `LLMContentRefusedError`.

### Middleware (`magent.middleware`)
```python
from magent import Middleware, compose, MiddlewareAgent, LoggingMiddleware, RateLimitMiddleware, SizeLimitMiddleware, RedactionMiddleware

async def run = await compose(inner_async_call, [mw1, mw2])
agent = MiddlewareAgent(inner_agent, [LoggingMiddleware(), RateLimitMiddleware(4), RedactionMiddleware({"token"})])
```
- `Middleware` is a `Protocol` with `before(inv)`, `after(inv, response)` and
  `on_error(inv, error)` (all async). `Invocation` exposes
  `agent_name`, `state`, `runtime`, `started_at`, `meta`.
- `compose` runs `before` in registration order and `after` in reverse. An
  exception propagates unchanged unless a middleware converts it in `on_error`.
  Middleware must not silently mutate framework state — observability-only
  changes go through `inv.meta`.
- `MiddlewareAgent(BaseAgent)` wraps an inner agent so the executor stays
  unchanged (retry/timeout/cancellation remain owned by `run_node`).
- Built-ins: `LoggingMiddleware`, `RateLimitMiddleware` (async semaphore),
  `SizeLimitMiddleware` (input/output byte caps), `RedactionMiddleware` (redacts
  sensitive fields into `inv.meta` only).

### Current limits (phase 6)
No vendor SDK bundled in core; only `openai` is shipped as an optional, lazily
imported adapter. `MiddlewareAgent` only wraps a single agent's `run`; graph-
level middleware composition is a later concern.

## Phase 8 — observability and evaluation (implemented)

Phase 8 does not change the execution semantics documented above. It adds a
read-only, framework-neutral observation and experiment contract under
`src/magent/observability` and `benchmarks/`; it is optional and must not make
EventBus data a source of state or recovery. Observability is enabled via the
VulnTell CLI flag `--trace <path>`, which emits `<path>.jsonl` (one `Trace`/`Span`
per line) and `<path>.summary.json` (`RunSummary`).

### Observation models (implemented)

```python
from magent.observability import Trace, Span, SpanStatus, RunSummary, build_observability, redact

trace, spans, summary = build_observability(
    report,                       # magent.core.executor.ExecutionReport
    workflow_id="graph",
    workflow_version="1",
    state_schema_version=state_schema_hash(VulnTellState),
    trace_id=None,                # generated (uuid4/sha256) when omitted
    checkpoint_records=None,      # list of recorded checkpoint objects
    redact_fields={"token"},      # extra keys to redact
)

# Trace: trace_id, run_id, workflow_id, workflow_version, state_schema_version,
#        started_at, finished_at, status, metadata
# Span:  span_id, trace_id, parent_span_id, node_id, agent_name, attempt,
#        attempt_role, queued_ms, duration_ms, status, error_type, retry_reason,
#        metadata
# RunSummary: trace_id, node_count, success_count, failure_count, cancelled_count,
#        not_executed_count, skipped_count, retry_count, timeout_count,
#        peak_concurrency, checkpoint_writes, recovery_count, replayed_nodes,
#        duration_ms, resource_samples, event_count
```

`build_observability` derives spans from the `ExecutionReport` `steps` (one attempt
→ one `Span`, with `SpanStatus` = `success`/`failed`/`timeout`/`cancelled`/
`not_executed`), and enriches `RunSummary` from retry/timeout/resume/checkpoint
counts. `redact(value, …)` truncates long strings, bounds depth/keys/list length,
and replaces secret keys (`api_key`, `token`, `secret`, `password`, `authorization`,
`cookie`) with `<redacted>`; observation data never records raw external text or
credentials. A `TraceCollector` can `attach(bus)` to an `EventBus` and add
`event_count`/`event_topics` to `Trace.metadata` without affecting execution.

### Experiment result (implemented)

`benchmarks/runner.run_scenario(config, scenario_fn, *, clock=time.monotonic)`
returns a `ScenarioResult` whose `to_dict()` always includes `experiment_id`,
`scenario_id`, `dataset_id`, `dataset_version`, `parser_version`, `dedup_version`,
`metric_version`, `framework_version`, `environment`, `concurrency`, `repetitions`
and `sample_count`, plus `n`, mean, median, p95, min, max. Scenarios (all offline,
deterministic): `run_sequential_baseline`, `run_parallel`, `run_recovery`,
`run_reliability`. `benchmarks/quality.evaluate_vulntell_quality(meta, final_state)`
returns a `QualityReport` with `sample_count`, `insufficient_data`,
`standardization`, `dedupe` (precision/recall/F1 only when ground truth exists),
`cross_source_consistency`, `report_completeness`, `partial_failure_usable`,
`metric_reproducible`. `benchmarks/reference_comparison.collect_reference_comparison()`
records `framework`, `version`, `behavior_note` and `status="not_comparable"` for
LangGraph/AutoGen/CrewAI; `to_comparison_report` always sets `ranking=None` and
`comparable=False`. If the declared sample threshold is not met, emit
`insufficient_data` and do not rank frameworks or sources.

Run the suite with `python -m benchmarks.cli --out benchmarks/out` (writes
`results.json`, `scenarios.csv`, `REPORT.md`). See `benchmarks/README.md`.

## Phase 7 — VulnTell vertical example (implemented)

Documented in [`PHASE7.md`](../phases/PHASE7.md). VulnTell
consumes the public `magent` API from `examples/vulntell`; its CVE,
source-observation, normalization, metric and report models are **not** part of
the framework core.

### Offline run
```bash
python -m examples.vulntell            # human-readable report (FakeProvider explanation)
python -m examples.vulntell --json     # machine-readable Report
python -m examples.vulntell --no-llm   # deterministic, no LLM
python -m examples.vulntell --faulty cnvd   # inject a source failure (partial report)
python -m examples.vulntell --resume --run-id <id> --checkpoint run.db  # recover
```

### `build_vulntell_graph(meta, store, sink, provider=None, *, fixture_dir=None, faulty_sources=None)`
Builds the concurrent, recoverable graph: `dispatch → (collect_nvd ‖ collect_cnvd)
→ (normalize_nvd ‖ normalize_cnvd) → dedupe → persist (side-effect tool through
SideEffectSink) → evaluate → report → END`. `meta` is a `DatasetMeta` (frozen
dataset/version/window). `store` is a `VulnTellStore` (SQLite, idempotent upsert).
`provider` is optional (`FakeProvider` by default in the CLI; `None` disables LLM).
Source branches write disjoint state keys and merge via `VulnTellState.reducers`.

### `VulnTellState`
A pydantic `State` carrying `meta`, `raw`, `observations_by_source`, `canonical`,
`pending`, `quality_issues`, `source_status`, `failed_sources`, `metrics`, `report`.
Cross-branch fields (`raw`, `observations_by_source`, `source_status`) merge via
reducers; `failed_sources` extends. All timestamps serialize to ISO strings so the
state is checkpoint-safe without touching the `magent` core.

### Determinism & safety
The graph runs fully offline (fixture sources, deterministic metrics). The LLM
provider only generates a non-binding textual explanation in `report.llm_explanation`;
it never alters the deterministic metrics or canonical data, and a provider failure
is captured in `report.llm_failed` while the structured report still succeeds.
