"""Single-process concurrent graph executor (phase 3 + phase 4 + phase 5).

Walks a DAG from the entry point to ``END``. Independent nodes run concurrently
under a bounded semaphore. Fan-out branches each start from the same state
snapshot; fan-in merges their partial updates through explicit reducers.
Failures are fail-fast: sibling branches in the same fan-out are cancelled,
not-yet-started dependents are recorded ``NOT_EXECUTED``.

Phase 4 adds node timeouts, bounded retries and caller cancellation on top of
the shared :func:`run_node` runner, so reliability semantics match the
sequential executor exactly.

Phase 5 adds an optional :class:`CheckpointStore`. With a store, every node
writes a ``NODE_STARTED`` snapshot before it runs and a ``NODE_COMMITTED``
record after it successfully commits its merged state + frontier. A crashed run
can be continued with :func:`GraphExecutor.resume`, which replays only the
uncommitted (or dangling) nodes from the last committed boundary. Without a
store, behaviour is identical to phase 4 and no I/O is performed.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from pydantic import BaseModel

from magent.core.agent import BaseAgent
from magent.core.errors import AgentError, StateMergeConflictError, StateUpdateError
from magent.core.executor import ExecutionReport, StepRecord
from magent.core.result import AgentResult, ExecutionStatus
from magent.core.runtime import Runtime, new_run_id
from magent.core.state import merge_updates
from magent.events.model import Event

from .model import CompiledGraph, END

_log = logging.getLogger("magent.graph")


class GraphExecutor:
    def __init__(
        self,
        graph: CompiledGraph,
        *,
        run_id: str | None = None,
        clock=None,
        max_concurrency: int | None = None,
        event_bus=None,
        reliability=None,
        sleeper=asyncio.sleep,
        rng=random.random,
        checkpoint_store=None,
        workflow_id: str = "graph",
        workflow_version: str = "1",
    ) -> None:
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {max_concurrency!r}")
        self._graph = graph
        self._run_id = run_id
        self._clock = clock or time.time
        self._max_concurrency = max_concurrency
        self._bus = event_bus
        self._reliability = reliability
        self._sleeper = sleeper
        self._rng = rng
        self._checkpoint_store = checkpoint_store
        self._workflow_id = workflow_id
        self._workflow_version = workflow_version

    async def run(self, initial_state: BaseModel) -> tuple[BaseModel, ExecutionReport]:
        return await self._execute(initial_state, resumed=False, resume_run_id=None)

    async def resume(
        self, run_id: str, initial_state: BaseModel
    ) -> tuple[BaseModel, ExecutionReport]:
        if self._checkpoint_store is None:
            raise ValueError("resume requires a checkpoint_store")
        return await self._execute(initial_state, resumed=True, resume_run_id=run_id)

    async def _execute(
        self, initial_state: BaseModel, *, resumed: bool, resume_run_id: str | None
    ) -> tuple[BaseModel, ExecutionReport]:
        from magent.checkpoint.models import (
            CheckpointPhase,
            CheckpointRecord,
            RunRecord,
            state_schema_hash,
            state_type_name,
        )
        from magent.checkpoint.recovery import build_graph_resume, load_history
        from magent.reliability.runner import run_node
        from magent.reliability.policy import ReliabilityPolicy

        policy = self._reliability or ReliabilityPolicy()
        graph = self._graph
        store = self._checkpoint_store
        state_cls = type(initial_state)
        state_type = state_type_name(state_cls)
        state_hash = state_schema_hash(state_cls)
        run_id = resume_run_id or self._run_id or new_run_id()
        started_ts = self._clock()

        rc: dict = {}
        if resumed:
            _run, checkpoints = await load_history(
                store,
                run_id,
                state_cls=state_cls,
                workflow_id=self._workflow_id,
                workflow_version=self._workflow_version,
                initial_state=initial_state,
            )
            rc = build_graph_resume(checkpoints, graph, state_cls)

        input_state: dict[str, BaseModel] = {graph.entry: initial_state}
        out_state: dict[str, BaseModel] = {}
        updates: dict[str, dict] = {}
        status: dict[str, ExecutionStatus | None] = {n: None for n in graph.nodes}
        recorded: set[str] = set()
        started_set: set[str] = set()
        activated: dict[str, set[str]] = {}
        steps: dict[str, StepRecord] = {}
        branch_id = _compute_branch_ids(graph)
        ready_at: dict[str, float] = {}
        failed = False
        fail_branch: str | None = None
        order = 0
        running = 0
        peak = 0
        sem = asyncio.Semaphore(self._max_concurrency) if self._max_concurrency else None
        tasks: dict[str, asyncio.Task] = {}
        replayed: list[str] = []

        seq = [0]
        cp_lock = asyncio.Lock()

        async def _cp(phase, **kw) -> None:
            if store is None:
                return
            async with cp_lock:
                rec = CheckpointRecord(
                    run_id=run_id,
                    workflow_id=self._workflow_id,
                    workflow_version=self._workflow_version,
                    state_type=state_type,
                    state_schema_hash=state_hash,
                    checkpoint_seq=seq[0],
                    phase=phase,
                    created_at=self._clock(),
                    **kw,
                )
                await store.append(rec)
                seq[0] += 1

        if resumed:
            for n, st in rc["out_state"].items():
                out_state[n] = st
                updates[n] = rc["updates"][n]
                status[n] = ExecutionStatus.SUCCESS
            for n, act in rc["activated"].items():
                activated[n] = set(act)
            for n, step in rc["committed_steps"].items():
                steps[n] = step
                recorded.add(n)
            order = len(steps)
            seq[0] = rc["from_seq"] + 1
            abandoned = rc["abandoned"]
        else:
            abandoned = 0
            if store is not None:
                await store.create_run(
                    RunRecord(
                        run_id=run_id,
                        workflow_id=self._workflow_id,
                        workflow_version=self._workflow_version,
                        state_type=state_type,
                        state_schema_hash=state_hash,
                        initial_state=initial_state.model_dump(),
                        status=CheckpointPhase.RUN_STARTED.value,
                        created_at=started_ts,
                        updated_at=started_ts,
                    )
                )
                await _cp(CheckpointPhase.RUN_STARTED, input_state=initial_state.model_dump())

        preds = _compute_preds(graph)
        reducers = getattr(type(initial_state), "reducers", None) or {}

        def preds_ready(n: str) -> bool:
            pr = preds.get(n, [])
            if not pr:
                return True
            for (p, kind) in pr:
                if status[p] is None:
                    return False
                if kind == "conditional" and n not in activated.get(p, set()):
                    return False
            return True

        def should_not_execute(n: str) -> bool:
            if not failed:
                return False
            for (p, _k) in preds.get(n, []):
                if status[p] in (ExecutionStatus.FAILED, ExecutionStatus.CANCELLED):
                    return True
            if fail_branch is not None and branch_id.get(n) == fail_branch and status[n] is None:
                return True
            return False

        def record(n, st, start, end, wait, message=None, error=None, attempts=None, terminal_reason=None):
            nonlocal order
            steps[n] = StepRecord(
                order=order,
                node_id=n,
                agent_name=graph.nodes[n].name,
                status=st,
                started_at=start,
                finished_at=end,
                duration_ms=(end - start) * 1000,
                message=message,
                error=error,
                wait_ms=wait,
                attempts=attempts or [],
                terminal_reason=terminal_reason,
            )
            recorded.add(n)
            status[n] = st
            order += 1

        def compute_input(n: str) -> BaseModel:
            pr = preds.get(n, [])
            if not pr:
                return initial_state
            if n in graph.joins:
                parents = list(graph.joins[n])
                base = input_state[parents[0]]
                merged = base.model_dump()
                branch_keys: set[str] = set()
                for p in parents:
                    upd = updates.get(p)
                    if not upd:
                        continue
                    for key, value in upd.items():
                        if key in reducers:
                            merged[key] = reducers[key](merged[key], value)
                        elif key in branch_keys:
                            raise StateMergeConflictError(
                                f"field '{key}' updated by multiple parallel branches without a reducer"
                            )
                        else:
                            merged[key] = value
                            branch_keys.add(key)
                return type(initial_state).model_validate(merged)
            (p, _k) = pr[0]
            return out_state[p]

        async def on_terminal(n: str, st: ExecutionStatus) -> None:
            nonlocal failed, fail_branch, running, peak
            if st in (ExecutionStatus.FAILED, ExecutionStatus.CANCELLED):
                failed = True
                if fail_branch is None:
                    fail_branch = branch_id.get(n)
                if fail_branch is not None:
                    for rn, t in list(tasks.items()):
                        if rn != n and branch_id.get(rn) == fail_branch:
                            t.cancel()
            if self._bus is not None:
                topic = {
                    ExecutionStatus.SUCCESS: "agent.completed",
                    ExecutionStatus.FAILED: "agent.failed",
                    ExecutionStatus.SKIPPED: "agent.skipped",
                    ExecutionStatus.CANCELLED: "agent.cancelled",
                }.get(st)
                if topic:
                    try:
                        await self._bus.publish(
                            Event(
                                topic=topic,
                                run_id=run_id,
                                source=n,
                                payload={
                                    "node_id": n,
                                    "agent_name": graph.nodes[n].name,
                                    "status": st.value,
                                },
                            )
                        )
                    except Exception:  # noqa: BLE001 - events are best-effort
                        pass

        async def run_one(n: str, rid: str) -> None:
            nonlocal running, peak
            agent: BaseAgent = graph.nodes[n]
            step_start = self._clock()
            wait = (step_start - ready_at[n]) * 1000 if ready_at.get(n) is not None else 0.0
            runtime = Runtime(
                run_id=rid,
                agent_name=agent.name,
                started_at=step_start,
                logger=logging.getLogger(f"magent.{n}"),
                clock=self._clock,
            )
            log: list = []

            async def emit(topic: str, payload: dict) -> None:
                if self._bus is not None:
                    try:
                        await self._bus.publish(
                            Event(topic=topic, run_id=rid, source=n, payload=payload)
                        )
                    except Exception:  # noqa: BLE001 - events are best-effort
                        pass

            await _cp(
                CheckpointPhase.NODE_STARTED,
                node_id=n,
                node_version=getattr(agent, "version", "1"),
                attempt=1,
                input_state=input_state[n].model_dump(),
            )
            try:
                if sem:
                    await sem.acquire()
                running += 1
                peak = max(peak, running)
                try:
                    outcome = await run_node(
                        agent,
                        input_state[n],
                        runtime,
                        policy=policy,
                        sleeper=self._sleeper,
                        rng=self._rng,
                        clock=self._clock,
                        emit=emit,
                        attempts_log=log,
                    )
                finally:
                    running -= 1
                    if sem:
                        sem.release()
            except asyncio.CancelledError:
                end = self._clock()
                record(
                    n,
                    ExecutionStatus.CANCELLED,
                    step_start,
                    end,
                    wait,
                    attempts=list(log),
                    terminal_reason="cancelled",
                )
                await on_terminal(n, ExecutionStatus.CANCELLED)
                return
            except Exception as exc:  # noqa: BLE001 - normalize to AgentError
                end = self._clock()
                err = AgentError(agent.name, rid, str(exc), cause=exc)
                record(
                    n,
                    ExecutionStatus.FAILED,
                    step_start,
                    end,
                    wait,
                    attempts=list(log),
                    terminal_reason="failed",
                    error={
                        "type": "AgentError",
                        "agent_name": agent.name,
                        "run_id": rid,
                        "message": str(err),
                        "cause": type(exc).__name__,
                    },
                )
                await on_terminal(n, ExecutionStatus.FAILED)
                return

            # Process the terminal outcome from the runner.
            if outcome.status == ExecutionStatus.SKIPPED:
                end = self._clock()
                out_state[n] = input_state[n]
                record(
                    n,
                    ExecutionStatus.SKIPPED,
                    step_start,
                    end,
                    wait,
                    message=outcome.result.message if outcome.result else None,
                    attempts=outcome.attempts,
                    terminal_reason=outcome.terminal_reason,
                )
                await _cp(
                    CheckpointPhase.NODE_COMMITTED,
                    node_id=n,
                    node_version=getattr(agent, "version", "1"),
                    output_state=input_state[n].model_dump(),
                    updates={},
                    activated_nodes=None,
                    attempts=[a.model_dump() for a in outcome.attempts],
                )
                await on_terminal(n, ExecutionStatus.SKIPPED)
                return

            if outcome.status == ExecutionStatus.SUCCESS:
                result = outcome.result
                assert result is not None
                try:
                    new_state = merge_updates(input_state[n], result.updates)
                except StateUpdateError as exc:
                    end = self._clock()
                    record(
                        n,
                        ExecutionStatus.FAILED,
                        step_start,
                        end,
                        wait,
                        attempts=outcome.attempts,
                        terminal_reason="failed",
                        error={"type": "StateUpdateError", "reason": exc.reason},
                    )
                    await on_terminal(n, ExecutionStatus.FAILED)
                    return

                updates[n] = dict(result.updates)
                out_state[n] = new_state
                message = result.message

                if n in graph.conditional:
                    router, mapping = graph.conditional[n]
                    try:
                        if asyncio.iscoroutinefunction(router):
                            label = await router(new_state)
                        else:
                            label = router(new_state)
                    except Exception as exc:  # noqa: BLE001 - normalize routing failure
                        end = self._clock()
                        record(
                            n,
                            ExecutionStatus.FAILED,
                            step_start,
                            end,
                            wait,
                            attempts=outcome.attempts,
                            terminal_reason="failed",
                            error={
                                "type": "GraphRoutingError",
                                "message": str(exc),
                                "cause": type(exc).__name__,
                            },
                        )
                        await on_terminal(n, ExecutionStatus.FAILED)
                        return
                    if label not in mapping:
                        end = self._clock()
                        record(
                            n,
                            ExecutionStatus.FAILED,
                            step_start,
                            end,
                            wait,
                            attempts=outcome.attempts,
                            terminal_reason="failed",
                            error={
                                "type": "GraphRoutingError",
                                "reason": f"unknown routing label '{label}'",
                            },
                        )
                        await on_terminal(n, ExecutionStatus.FAILED)
                        return
                    target = mapping[label]
                    activated[n] = {target} if target != END else set()
                    for lab, tgt in mapping.items():
                        if (
                            lab != label
                            and tgt != END
                            and tgt not in recorded
                            and tgt not in started_set
                        ):
                            ts = self._clock()
                            record(tgt, ExecutionStatus.NOT_EXECUTED, ts, ts, 0.0)
                    end = self._clock()
                    record(
                        n,
                        ExecutionStatus.SUCCESS,
                        step_start,
                        end,
                        wait,
                        message=message,
                        attempts=outcome.attempts,
                        terminal_reason=outcome.terminal_reason,
                    )
                    await _cp(
                        CheckpointPhase.NODE_COMMITTED,
                        node_id=n,
                        node_version=getattr(agent, "version", "1"),
                        output_state=new_state.model_dump(),
                        updates=dict(result.updates),
                        activated_nodes=list(activated[n]),
                        attempts=[a.model_dump() for a in outcome.attempts],
                    )
                    await on_terminal(n, ExecutionStatus.SUCCESS)
                    return

                end = self._clock()
                record(
                    n,
                    ExecutionStatus.SUCCESS,
                    step_start,
                    end,
                    wait,
                    message=message,
                    attempts=outcome.attempts,
                    terminal_reason=outcome.terminal_reason,
                )
                await _cp(
                    CheckpointPhase.NODE_COMMITTED,
                    node_id=n,
                    node_version=getattr(agent, "version", "1"),
                    output_state=new_state.model_dump(),
                    updates=dict(result.updates),
                    activated_nodes=None,
                    attempts=[a.model_dump() for a in outcome.attempts],
                )
                await on_terminal(n, ExecutionStatus.SUCCESS)
                return

            # Terminal FAILED (includes timeout).
            end = self._clock()
            record(
                n,
                ExecutionStatus.FAILED,
                step_start,
                end,
                wait,
                message=outcome.result.message if outcome.result else None,
                error=outcome.error,
                attempts=outcome.attempts,
                terminal_reason=outcome.terminal_reason,
            )
            await on_terminal(n, ExecutionStatus.FAILED)

        # Main scheduling loop.
        caller_cancelled = False
        try:
            while not all(status[n] is not None for n in graph.nodes):
                progress = False
                for n in list(graph.nodes):
                    if n in started_set or status[n] is not None:
                        continue
                    if not preds_ready(n):
                        continue
                    if failed and should_not_execute(n):
                        ts = self._clock()
                        record(n, ExecutionStatus.NOT_EXECUTED, ts, ts, 0.0)
                        progress = True
                        continue
                    try:
                        input_state[n] = compute_input(n)
                    except StateMergeConflictError as exc:
                        ts = self._clock()
                        record(
                            n,
                            ExecutionStatus.FAILED,
                            ts,
                            ts,
                            0.0,
                            attempts=[],
                            terminal_reason="failed",
                            error={"type": "StateMergeConflictError", "reason": exc.reason},
                        )
                        await on_terminal(n, ExecutionStatus.FAILED)
                        progress = True
                        continue
                    ready_at[n] = self._clock()
                    started_set.add(n)
                    if resumed:
                        replayed.append(n)
                    tasks[n] = asyncio.create_task(run_one(n, run_id))
                    progress = True

                if tasks:
                    done_set, _ = await asyncio.wait(
                        set(tasks.values()), return_when=asyncio.FIRST_COMPLETED
                    )
                    for t in done_set:
                        for rn, tk in list(tasks.items()):
                            if tk is t:
                                del tasks[rn]
                                break
                    progress = True

                if not progress:
                    for n in list(graph.nodes):
                        if status[n] is None and n not in started_set:
                            ts = self._clock()
                            record(n, ExecutionStatus.NOT_EXECUTED, ts, ts, 0.0)
                    break
        except asyncio.CancelledError:
            caller_cancelled = True
            for t in tasks.values():
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks.values(), return_exceptions=True)
            for n in graph.nodes:
                if status[n] is None:
                    ts = self._clock()
                    if n in started_set:
                        record(
                            n,
                            ExecutionStatus.CANCELLED,
                            ts,
                            ts,
                            0.0,
                            terminal_reason="cancelled",
                        )
                    else:
                        record(n, ExecutionStatus.NOT_EXECUTED, ts, ts, 0.0)

        # Safety net: any node never recorded (should not happen).
        for n in list(graph.nodes):
            if n not in recorded:
                ts = self._clock()
                record(n, ExecutionStatus.NOT_EXECUTED, ts, ts, 0.0)

        finished_ts = self._clock()
        steps_list = [steps[n] for n in sorted(steps, key=lambda x: steps[x].order)]
        final_state = _compute_final_state(steps, out_state, status, graph, initial_state)
        retry_count = sum(max(0, len(s.attempts) - 1) for s in steps_list)
        timeout_count = sum(
            1
            for s in steps_list
            for a in s.attempts
            if a.error and a.error.get("type") == "NodeTimeoutError"
        )
        if store is not None:
            if caller_cancelled:
                phase = CheckpointPhase.RUN_CANCELLED
            elif not failed and all(
                s in (ExecutionStatus.SUCCESS, ExecutionStatus.SKIPPED) for s in status.values()
            ):
                phase = CheckpointPhase.RUN_COMPLETED
            else:
                phase = CheckpointPhase.RUN_FAILED
            await _cp(phase, output_state=(final_state if final_state is not None else initial_state).model_dump())
            await store.update_run_status(run_id, phase.value)
        report = ExecutionReport(
            run_id=run_id,
            initial_state=initial_state.model_dump(),
            final_state=final_state.model_dump() if final_state is not None else initial_state.model_dump(),
            steps=steps_list,
            started_at=started_ts,
            finished_at=finished_ts,
            duration_ms=(finished_ts - started_ts) * 1000,
            success=not failed
            and all(
                s in (ExecutionStatus.SUCCESS, ExecutionStatus.SKIPPED) for s in status.values()
            )
            and not caller_cancelled,
            peak_concurrency=peak,
            event_stats=self._bus.stats() if self._bus is not None else None,
            cancellation_reason="caller" if caller_cancelled else None,
            retry_count=retry_count,
            timeout_count=timeout_count,
            resumed=resumed,
            resumed_from_seq=rc["from_seq"] if resumed else None,
            abandoned_attempts=abandoned,
            replayed_nodes=replayed,
        )
        return (final_state if final_state is not None else initial_state), report


def _compute_preds(graph: CompiledGraph) -> dict[str, list[tuple[str, str]]]:
    preds: dict[str, list[tuple[str, str]]] = {n: [] for n in graph.nodes}
    for source, target in graph.edges.items():
        if target != END:
            preds[target].append((source, "normal"))
    for source, targets in graph.parallel.items():
        for target in targets:
            if target != END:
                preds[target].append((source, "parallel"))
    for join_node, parents in graph.joins.items():
        for parent in parents:
            preds[join_node].append((parent, "join"))
    for source, (router, mapping) in graph.conditional.items():
        for target in mapping.values():
            if target != END:
                preds[target].append((source, "conditional"))
    return preds


def _compute_branch_ids(graph: CompiledGraph) -> dict[str, str | None]:
    bid: dict[str, str | None] = {graph.entry: None}
    stack = [graph.entry]
    while stack:
        n = stack.pop()
        if n in graph.edges and graph.edges[n] != END:
            t = graph.edges[n]
            bid.setdefault(t, bid.get(n))
            stack.append(t)
        if n in graph.parallel:
            for t in graph.parallel[n]:
                if t != END:
                    bid[t] = n
                    stack.append(t)
        if n in graph.conditional:
            for t in graph.conditional[n][1].values():
                if t != END:
                    bid.setdefault(t, bid.get(n))
                    stack.append(t)
    return bid


def _leads_to_end(n: str, graph: CompiledGraph) -> bool:
    if n in graph.edges and graph.edges[n] == END:
        return True
    if n in graph.parallel and END in graph.parallel[n]:
        return True
    if n in graph.conditional and END in graph.conditional[n][1].values():
        return True
    return False


def _compute_final_state(steps, out_state, status, graph, initial_state) -> BaseModel | None:
    candidates = [
        n
        for n in graph.nodes
        if status.get(n) in (ExecutionStatus.SUCCESS, ExecutionStatus.SKIPPED)
        and _leads_to_end(n, graph)
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda x: steps[x].order)
    return out_state.get(best)
