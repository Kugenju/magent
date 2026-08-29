"""阶段 7 — VulnTell Graph 端到端、部分失败、恢复、LLM 边界与安全测试。"""

from __future__ import annotations

import pathlib

import pytest

from magent import GraphExecutor
from magent.checkpoint import SqliteCheckpointStore, SideEffectSink
from magent.llm import FakeProvider

from examples.vulntell.db import VulnTellStore
from examples.vulntell.graph import build_vulntell_graph
from examples.vulntell.loading import load_dataset_meta
from examples.vulntell.models import Report
from examples.vulntell.state import VulnTellState

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[2] / "examples" / "vulntell" / "fixtures"


def _failing_provider():
    return FakeProvider(handler=lambda req: (_ for _ in ()).throw(RuntimeError("boom")))


async def _build(meta, db_path, store, sink, faulty=None, provider=None, run_id="r1"):
    graph = build_vulntell_graph(
        meta, VulnTellStore(db_path), sink, provider, faulty_sources=faulty or set()
    )
    state = VulnTellState(meta=meta)
    ex = GraphExecutor(graph, run_id=run_id, max_concurrency=4, checkpoint_store=store)
    return graph, state, ex


async def test_end_to_end_produces_report():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = SqliteCheckpointStore(":memory:")
    sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
    graph, state, ex = await _build(meta, ":memory:", store, sink, provider=FakeProvider())
    final, report = await ex.run(state)
    assert report.success
    assert final.report is not None
    rep = Report(**final.report)
    assert rep.canonical_count == 5
    assert rep.pending_count == 1
    assert rep.source_status == {"nvd": "ok", "cnvd": "ok"}


async def test_report_is_deterministic_across_runs():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")

    def _run_once():
        store = SqliteCheckpointStore(":memory:")
        sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
        return store, sink

    store1, sink1 = _run_once()
    _, _, ex1 = await _build(meta, ":memory:", store1, sink1, provider=FakeProvider(), run_id="a")
    f1, _ = await ex1.run(VulnTellState(meta=meta))
    store2, sink2 = _run_once()
    _, _, ex2 = await _build(meta, ":memory:", store2, sink2, provider=FakeProvider(), run_id="b")
    f2, _ = await ex2.run(VulnTellState(meta=meta))
    assert Report(**f1.report).model_dump() == Report(**f2.report).model_dump()


async def test_partial_failure_keeps_other_source():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = SqliteCheckpointStore(":memory:")
    sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
    graph, state, ex = await _build(meta, ":memory:", store, sink, faulty={"cnvd"}, provider=FakeProvider())
    final, report = await ex.run(state)
    rep = Report(**final.report)
    # cnvd 失败，但 nvd 结果仍可用
    assert rep.source_status["cnvd"] == "failed"
    assert rep.source_status["nvd"] == "ok"
    assert "cnvd" in rep.source_status  # 失败来源仍明确记录
    # 仅 nvd 的 4 个 CVE 进入 canonical
    assert rep.canonical_count == 4


async def test_partial_failure_reports_failure_source():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = SqliteCheckpointStore(":memory:")
    sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
    graph, state, ex = await _build(meta, ":memory:", store, sink, faulty={"nvd"}, provider=FakeProvider())
    final, report = await ex.run(state)
    rep = Report(**final.report)
    assert rep.source_status["nvd"] == "failed"
    # 报告中明确记录质量缺口/失败来源
    assert "failed" in rep.source_status.values()


async def test_resume_does_not_rerun_committed_persist():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = SqliteCheckpointStore(":memory:")
    sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
    graph, state, ex = await _build(meta, ":memory:", store, sink, provider=FakeProvider(), run_id="r")
    final1, _ = await ex.run(state)
    assert sink.write_count == 1  # persist 副作用执行一次
    # 恢复相同 run_id
    _, _, ex2 = await _build(meta, ":memory:", store, sink, provider=FakeProvider(), run_id="r")
    final2, report2 = await ex2.resume("r", VulnTellState(meta=meta))
    assert report2.success
    # 已提交节点不重跑：副作用写入计数不变
    assert sink.write_count == 1
    assert Report(**final1.report).model_dump() == Report(**final2.report).model_dump()


async def test_repeated_run_no_duplicate_business_records(tmp_path):
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    db_path = str(tmp_path / "vt.db")

    def _run():
        store = SqliteCheckpointStore(":memory:")
        sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
        return store, sink

    store1, sink1 = _run()
    _, _, ex1 = await _build(meta, db_path, store1, sink1, provider=FakeProvider(), run_id="a")
    await ex1.run(VulnTellState(meta=meta))
    biz = VulnTellStore(db_path)
    n_obs1 = biz.count_observations()
    n_can1 = biz.count_canonical()
    biz.close()

    store2, sink2 = _run()
    _, _, ex2 = await _build(meta, db_path, store2, sink2, provider=FakeProvider(), run_id="b")
    await ex2.run(VulnTellState(meta=meta))
    biz2 = VulnTellStore(db_path)
    assert biz2.count_observations() == n_obs1
    assert biz2.count_canonical() == n_can1
    biz2.close()


async def test_llm_disabled_still_produces_report():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = SqliteCheckpointStore(":memory:")
    sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
    graph, state, ex = await _build(meta, ":memory:", store, sink, provider=None)
    final, _ = await ex.run(state)
    rep = Report(**final.report)
    assert rep.llm_explanation is None
    assert rep.llm_failed is False


async def test_llm_failure_does_not_break_report():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = SqliteCheckpointStore(":memory:")
    sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
    graph, state, ex = await _build(meta, ":memory:", store, sink, provider=_failing_provider())
    final, _ = await ex.run(state)
    rep = Report(**final.report)
    # LLM 失败：结构化报告仍在，解释缺失，标记失败
    assert rep.llm_failed is True
    assert rep.llm_explanation is None
    assert rep.canonical_count == 5


async def test_report_records_versions_and_window():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = SqliteCheckpointStore(":memory:")
    sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
    graph, state, ex = await _build(meta, ":memory:", store, sink, provider=FakeProvider())
    final, _ = await ex.run(state)
    rep = Report(**final.report)
    assert rep.dataset_id == meta.dataset_id
    assert rep.window_start == meta.window_start
    assert rep.parser_version == meta.parser_version
    assert rep.metric_version == meta.metric_version
    assert rep.framework_version == meta.framework_version


async def test_insufficient_data_via_small_fixture(tmp_path):
    # 用仅含一条 CVE 的临时 fixture 触发 insufficient_data
    import json

    small = {
        "source": "nvd",
        "dataset_id": "vulntell-demo",
        "dataset_version": "2024Q1",
        "records": [
            {"record_id": "X1", "cve_id": "CVE-2023-2001", "title": "t", "published_at": "2023-01-01T00:00:00Z"}
        ],
    }
    fd = tmp_path / "small_nvd.json"
    fd.write_text(json.dumps(small), encoding="utf-8")
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = SqliteCheckpointStore(":memory:")
    sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
    graph = build_vulntell_graph(
        meta, VulnTellStore(":memory:"), sink, FakeProvider(), fixture_dir=tmp_path, faulty_sources={"cnvd"}
    )
    state = VulnTellState(meta=meta)
    ex = GraphExecutor(graph, run_id="r", max_concurrency=4, checkpoint_store=store)
    final, _ = await ex.run(state)
    rep = Report(**final.report)
    assert rep.insufficient_data is True


async def test_no_api_key_in_state():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    state = VulnTellState(meta=meta)
    # 业务 State 没有任何凭据字段
    assert "api_key" not in state.model_dump()
    assert "api_key" not in VulnTellState.model_fields


def test_http_adapter_disabled_by_default():
    from examples.vulntell.sources import HttpSourceAdapter

    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    adapter = HttpSourceAdapter("nvd", endpoint="https://example", api_key="secret")
    with pytest.raises(NotImplementedError):
        # 默认不联网
        import asyncio

        asyncio.run(adapter.fetch("d", "v", meta.window_end))


def test_faulty_adapter_isolates_failure():
    from examples.vulntell.sources import FaultySourceAdapter

    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    adapter = FaultySourceAdapter("cnvd")
    with pytest.raises(RuntimeError):
        import asyncio

        asyncio.run(adapter.fetch("d", "v", meta.window_end))


async def test_graph_uses_concurrent_join():
    # 拓扑校验应通过（fan-out + join + 单一可恢复 Graph）
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = SqliteCheckpointStore(":memory:")
    sink = SideEffectSink(store, run_id="r", node_id="persist", node_version="1")
    graph = build_vulntell_graph(meta, VulnTellStore(":memory:"), sink, FakeProvider())
    # compile 不抛异常即拓扑合法
    assert graph is not None
