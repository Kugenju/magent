"""阶段 8 — 实验 runner / 场景 / 质量评测 / 对比记录测试。"""

from __future__ import annotations

import asyncio
import datetime as dt
import pathlib

from benchmarks.config import ExperimentConfig
from benchmarks.quality import evaluate_vulntell_quality, run_pipeline
from benchmarks.reference_comparison import collect_reference_comparison, to_comparison_report
from benchmarks.runner import run_scenario
from benchmarks.scenarios import run_parallel, run_recovery, run_reliability, run_sequential_baseline
from benchmarks.stats import summarize
from examples.vulntell.db import VulnTellStore
from examples.vulntell.graph import build_vulntell_graph
from examples.vulntell.loading import load_dataset_meta
from examples.vulntell.metrics import compute_metrics
from examples.vulntell.models import CanonicalVulnerability, QualityIssue, SourceObservation
from examples.vulntell.state import VulnTellState
from magent import GraphExecutor
from magent.checkpoint import SideEffectSink, SqliteCheckpointStore
from magent.checkpoint.models import state_schema_hash
from magent.observability import build_observability


class _Clock:
    def __init__(self):
        self._t = [0.0]

    def __call__(self):
        self._t[0] += 1.0
        return self._t[0]


# ---- config / stats ----
def test_experiment_config_requires_id():
    import pytest

    with pytest.raises(Exception):
        ExperimentConfig(scenario_id="x")


def test_experiment_config_env():
    c = ExperimentConfig(experiment_id="e", scenario_id="x")
    env = c.environment()
    assert "python_version" in env and "framework_version" in env


def test_summarize_empty():
    s = summarize([])
    assert s["n"] == 0
    assert s["mean"] == 0.0


def test_summarize_stats():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    s = summarize(vals)
    assert s["n"] == 5
    assert s["mean"] == 3.0
    assert s["min"] == 1.0 and s["max"] == 5.0


# ---- scenarios ----
async def test_sequential_baseline_correct():
    c = ExperimentConfig(experiment_id="e", scenario_id="seq", repetitions=3)
    r = await run_scenario(c, run_sequential_baseline, clock=_Clock())
    assert r.all_correct
    assert r.stats["n"] == 3


async def test_parallel_correct():
    c = ExperimentConfig(experiment_id="e", scenario_id="par", concurrency=4, repetitions=3)
    r = await run_scenario(c, run_parallel, clock=_Clock())
    assert r.all_correct


async def test_recovery_correct():
    c = ExperimentConfig(experiment_id="e", scenario_id="rec", repetitions=3)
    r = await run_scenario(c, run_recovery, clock=_Clock())
    assert r.all_correct


async def test_reliability_records_retry_timeout():
    c = ExperimentConfig(experiment_id="e", scenario_id="rel", retry_max_attempts=3, timeout=0.001, repetitions=2)
    r = await run_scenario(c, run_reliability, clock=_Clock())
    assert r.all_correct
    assert r.runs[0].report["timeout_count"] >= 1
    assert r.runs[0].report["retry_count"] >= 2


async def test_determinism_across_concurrency():
    c1 = ExperimentConfig(experiment_id="a", scenario_id="seq", repetitions=1)
    c2 = ExperimentConfig(experiment_id="b", scenario_id="par", concurrency=2, repetitions=1)
    c3 = ExperimentConfig(experiment_id="c", scenario_id="par8", concurrency=8, repetitions=1)
    r1 = await run_scenario(c1, run_sequential_baseline, clock=_Clock())
    r2 = await run_scenario(c2, run_parallel, clock=_Clock())
    r3 = await run_scenario(c3, run_parallel, clock=_Clock())
    assert r1.runs[0].report["canonical_count"] == r2.runs[0].report["canonical_count"] == r3.runs[0].report["canonical_count"] == 5


async def test_scenario_result_contains_metadata():
    c = ExperimentConfig(experiment_id="e", scenario_id="seq", repetitions=2)
    r = await run_scenario(c, run_sequential_baseline, clock=_Clock())
    d = r.to_dict()
    assert d["dataset_id"] and d["dataset_version"] and d["framework_version"]
    assert d["sample_count"] == 2


# ---- quality ----
def test_quality_full_fixture():
    meta = load_dataset_meta("examples/vulntell/fixtures/dataset_meta.json")
    final = asyncio.run(run_pipeline())
    q = evaluate_vulntell_quality(meta, final)
    assert q.sample_count == 5
    assert q.insufficient_data is False
    assert q.dedupe["precision"] == 1.0 and q.dedupe["recall"] == 1.0 and q.dedupe["f1"] == 1.0
    assert q.cross_source_consistency is True
    assert q.metric_reproducible is True
    assert q.report_completeness is True


def test_quality_partial_failure_usable():
    meta = load_dataset_meta("examples/vulntell/fixtures/dataset_meta.json")
    final = asyncio.run(run_pipeline(faulty=("cnvd",)))
    q = evaluate_vulntell_quality(meta, final, faulty=("cnvd",))
    assert q.partial_failure_usable is True
    assert q.sample_count == 4


def test_quality_insufficient_data():
    meta = load_dataset_meta("examples/vulntell/fixtures/dataset_meta.json")
    state = VulnTellState(meta=meta, canonical=[], observations_by_source={}, quality_issues=[], source_status={})
    q = evaluate_vulntell_quality(meta, state, sample_threshold=2)
    assert q.insufficient_data is True
    assert q.dedupe["precision"] is None


def test_metric_reproducibility_direct():
    obs = [SourceObservation(source="nvd", source_record_id="r", cve_id="CVE-2023-1001", observed_at=dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc), raw_payload_hash="h", normalized_fields={})]
    canon = [CanonicalVulnerability(cve_id="CVE-2023-1001")]
    meta = load_dataset_meta("examples/vulntell/fixtures/dataset_meta.json")
    m1 = compute_metrics(obs, canon, [], [], meta, {})
    m2 = compute_metrics(obs, canon, [], [], meta, {})
    assert m1.model_dump() == m2.model_dump()


# ---- reference comparison ----
def test_reference_comparison_not_comparable():
    recs = collect_reference_comparison()
    assert len(recs) == 3
    assert all(r.status == "not_comparable" for r in recs)
    report = to_comparison_report(recs)
    assert report["ranking"] is None
    assert report["comparable"] is False


# ---- observability integration (VulnTell) ----
async def test_observability_integration_vulntell():
    meta = load_dataset_meta("examples/vulntell/fixtures/dataset_meta.json")
    await run_pipeline()
    store = VulnTellStore(":memory:")
    store.init_schema()
    sink = SideEffectSink(SqliteCheckpointStore(":memory:"), run_id="obs", node_id="persist", node_version="1")
    graph = build_vulntell_graph(meta, store, sink, None, fixture_dir=pathlib.Path("examples/vulntell/fixtures"), faulty_sources=set())
    fstate = VulnTellState(meta=meta)
    _final, report = await GraphExecutor(graph, run_id="obs", max_concurrency=4).run(fstate)
    store.close()
    schema = state_schema_hash(VulnTellState)
    t, spans, summary = build_observability(report, workflow_id="graph", workflow_version="1", state_schema_version=schema)
    node_ids = {s.node_id for s in spans}
    assert {"collect_nvd", "normalize_nvd", "dedupe", "persist", "evaluate", "report"} <= node_ids
    assert t.status == "success"
    assert summary.success_count >= 1


async def test_observability_isolation_matches_report():
    # 观测启用/关闭不改变 VulnTell 确定性报告
    f1 = await run_pipeline()
    f2 = await run_pipeline()
    assert f1.report == f2.report
    meta = load_dataset_meta("examples/vulntell/fixtures/dataset_meta.json")
    store = VulnTellStore(":memory:")
    store.init_schema()
    sink = SideEffectSink(SqliteCheckpointStore(":memory:"), run_id="obs2", node_id="persist", node_version="1")
    graph = build_vulntell_graph(meta, store, sink, None, fixture_dir=pathlib.Path("examples/vulntell/fixtures"))
    fstate = VulnTellState(meta=meta)
    _final, report = await GraphExecutor(graph, run_id="obs2", max_concurrency=4).run(fstate)
    store.close()
    schema = state_schema_hash(VulnTellState)
    t1, spans1, s1 = build_observability(report, workflow_id="graph", workflow_version="1", state_schema_version=schema)
    t2, spans2, s2 = build_observability(report, workflow_id="graph", workflow_version="1", state_schema_version=schema)
    assert t1.model_dump(exclude={"trace_id"}) == t2.model_dump(exclude={"trace_id"})
    assert len(spans1) == len(spans2)
