"""阶段 8 实验场景（Task 4）。

覆盖：串行基线、并行 DAG（多种并发度）、可靠（重试/超时）、Checkpoint 恢复。所有场景离线，
不联网、不调用真实 LLM。计时使用注入的单调时钟，正确性断言与性能统计分离。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import pathlib

from pydantic import BaseModel

from magent import BaseAgent, AgentResult, END, ExecutionStatus, GraphBuilder, GraphExecutor, SequentialExecutor
from magent.checkpoint import SqliteCheckpointStore, SideEffectSink
from magent.reliability import ReliabilityPolicy, RetryPolicy, TimeoutPolicy
from magent.reliability.errors import RetryableError

from examples.vulntell.db import VulnTellStore
from examples.vulntell.graph import build_vulntell_graph
from examples.vulntell.loading import load_dataset_meta
from examples.vulntell.models import Report
from examples.vulntell.state import VulnTellState

from .config import ExperimentConfig
from .runner import ScenarioRun

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[1] / "examples" / "vulntell" / "fixtures"


def _fixture_meta():
    return load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")


async def _run_vulntell(
    config: ExperimentConfig, *, concurrency, clock, faulty=(), use_checkpoint=False, run_id="bench"
):
    meta = _fixture_meta()
    store = VulnTellStore(":memory:")
    store.init_schema()
    checkpoint_store = SqliteCheckpointStore(":memory:") if use_checkpoint else None
    sink = SideEffectSink(checkpoint_store or SqliteCheckpointStore(":memory:"), run_id=run_id, node_id="persist", node_version="1")
    graph = build_vulntell_graph(
        meta, store, sink, None, fixture_dir=_FIXTURE_DIR, faulty_sources=set(faulty)
    )
    state = VulnTellState(meta=meta)
    ex = GraphExecutor(graph, run_id=run_id, max_concurrency=concurrency, checkpoint_store=checkpoint_store, clock=clock)
    start = clock() if clock else 0.0
    final, report = await ex.run(state)
    end = clock() if clock else 0.0
    duration = (end - start) * 1000 if clock else 0.0
    store.close()
    return final, report, duration


async def run_sequential_baseline(config: ExperimentConfig, *, clock=None, rng=None) -> ScenarioRun:
    """无并行基线（max_concurrency=1）。"""
    final, report, duration = await _run_vulntell(config, concurrency=1, clock=clock)
    rep = Report(**final.report) if final.report else None
    correct = bool(rep and report.success and rep.canonical_count == 5)
    return ScenarioRun(
        duration_ms=duration,
        correct=correct,
        report={"canonical_count": rep.canonical_count if rep else None, "source_status": rep.source_status if rep else None},
    )


async def run_parallel(config: ExperimentConfig, *, clock=None, rng=None) -> ScenarioRun:
    """并行 DAG，并发度来自 config.concurrency。"""
    final, report, duration = await _run_vulntell(config, concurrency=max(2, config.concurrency), clock=clock)
    rep = Report(**final.report) if final.report else None
    correct = bool(rep and report.success and rep.canonical_count == 5)
    return ScenarioRun(
        duration_ms=duration,
        correct=correct,
        report={"canonical_count": rep.canonical_count if rep else None, "source_status": rep.source_status if rep else None},
    )


async def run_recovery(config: ExperimentConfig, *, clock=None, rng=None) -> ScenarioRun:
    """Checkpoint 恢复：首次完整运行后 resume 同 run_id，结果应一致。"""
    meta = _fixture_meta()
    store = VulnTellStore(":memory:")
    store.init_schema()
    checkpoint_store = SqliteCheckpointStore(":memory:")
    sink = SideEffectSink(checkpoint_store, run_id="recovery", node_id="persist", node_version="1")
    graph = build_vulntell_graph(meta, store, sink, None, fixture_dir=_FIXTURE_DIR)
    state = VulnTellState(meta=meta)
    ex = GraphExecutor(graph, run_id="recovery", max_concurrency=4, checkpoint_store=checkpoint_store, clock=clock)
    start = clock() if clock else 0.0
    final1, report1 = await ex.run(state)
    # 进程“崩溃”后从已提交边界恢复
    final2, report2 = await ex.resume("recovery", VulnTellState(meta=meta))
    end = clock() if clock else 0.0
    duration = (end - start) * 1000 if clock else 0.0
    store.close()

    rep1 = Report(**final1.report)
    rep2 = Report(**final2.report)
    consistent = rep1.model_dump() == rep2.model_dump()
    correct = bool(report1.success and report2.success and consistent and report2.resumed and report2.replayed_nodes == [])
    return ScenarioRun(
        duration_ms=duration,
        correct=correct,
        report={"canonical_count": rep2.canonical_count, "resumed": report2.resumed, "replayed_nodes": report2.replayed_nodes},
        raw={"first": rep1.model_dump(), "second": rep2.model_dump()},
    )


class _FlakyAgent(BaseAgent):
    def __init__(self, name: str, fail_times: int) -> None:
        super().__init__(name)
        self._fail_times = fail_times
        self._calls = 0

    async def run(self, state, runtime):
        self._calls += 1
        if self._calls <= self._fail_times:
            raise RetryableError("transient")
        return AgentResult(updates={"flaky_ok": True})


class _SlowAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("slow")

    async def run(self, state, runtime):
        await asyncio.sleep(0.05)
        return AgentResult(updates={"slow_ok": True})


async def run_reliability(config: ExperimentConfig, *, clock=None, rng=None) -> ScenarioRun:
    """可靠场景：重试（flaky）与超时（slow）分支，观测终态与计数。"""
    fail_times = max(0, config.retry_max_attempts - 1)
    policy = ReliabilityPolicy(
        retry=RetryPolicy(max_attempts=max(1, config.retry_max_attempts)),
        timeout=TimeoutPolicy(node_timeout=config.timeout if config.timeout else 0.001),
    )
    graph = (
        GraphBuilder()
        .add_node("dispatch", _DispatchAgent())
        .add_node("flaky", _FlakyAgent("flaky", fail_times))
        .add_node("slow", _SlowAgent())
        .add_node("join", _JoinAgent())
        .set_entry_point("dispatch")
        .add_parallel_edges("dispatch", ["flaky", "slow"])
        .add_join("join", ["flaky", "slow"])
        .add_edge("join", END)
        .compile()
    )
    ex = GraphExecutor(graph, run_id="reliability", max_concurrency=2, reliability=policy, clock=clock)
    start = clock() if clock else 0.0
    _, report = await ex.run(_EmptyState())
    end = clock() if clock else 0.0
    duration = (end - start) * 1000 if clock else 0.0
    correct = report.timeout_count >= 1 and report.retry_count >= fail_times
    return ScenarioRun(
        duration_ms=duration,
        correct=correct,
        report={"retry_count": report.retry_count, "timeout_count": report.timeout_count, "success": report.success},
    )


class _EmptyState(BaseModel):
    pass


class _DispatchAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("dispatch")

    async def run(self, state, runtime):
        return AgentResult(updates={})


class _JoinAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("join")

    async def run(self, state, runtime):
        return AgentResult(updates={})
