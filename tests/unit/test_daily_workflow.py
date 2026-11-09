"""每日简报工作流（build_daily_vulntell_graph + DailyBriefingRunner）离线测试。

覆盖：N 源并行扇出与 reducer 合并、跨来源同 CVE 去重合并、失败来源降级、
持久化幂等管线、双路径对照接入、输出工件（dashboard/report/dual_path）。
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from apps.vulntell.pipeline.graph import build_daily_vulntell_graph

from _daily_helpers import (
    WINDOW_END,
    WINDOW_START,
    osv_mcp_adapter,
    run_offline_briefing,
)


def _make_meta(sources: list[str]):
    from apps.vulntell.domain.models import DatasetMeta

    return DatasetMeta(
        dataset_id="vulntell-daily",
        dataset_version="dev",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        framework_version="test",
        sources=sources,
    )


# ---------------------------------------------------------------- 图构建


async def test_daily_graph_requires_adapters():
    meta = _make_meta([])
    store, sink = object(), object()
    with pytest.raises(ValueError):
        build_daily_vulntell_graph(meta, store, sink, None, adapters={})


async def test_daily_graph_fanout_and_cross_source_merge(tmp_path):
    """KEV+OSV 同窗口并行采集：同 CVE 去重合并进同一 canonical（sources 并集）。"""
    result, _adapters, _server = await run_offline_briefing(tmp_path)
    state = result.pipeline.final_state
    assert state.source_status == {"cisa_kev": "ok", "osv_mcp": "ok"}
    obs_by_source = {s: len(lst) for s, lst in state.observations_by_source.items()}
    assert obs_by_source == {"cisa_kev": 2, "osv_mcp": 1}
    canonical = {c["cve_id"]: set(c["sources"]) for c in state.canonical}
    assert canonical == {
        "CVE-2024-3094": {"cisa_kev", "osv_mcp"},  # 跨来源合并
        "CVE-2024-32030": {"cisa_kev"},
    }
    assert result.pipeline.report is not None
    assert result.pipeline.report.canonical_count == 2
    assert result.pipeline.execution_report.success
    agent_names = sorted(step.agent_name for step in result.pipeline.execution_report.steps)
    assert agent_names == [
        "collect_cisa_kev", "collect_osv_mcp", "dedupe", "dispatch", "evaluate",
        "normalize_cisa_kev", "normalize_osv_mcp", "persist", "report",
    ]


async def test_failed_source_degrades_but_run_survives(tmp_path):
    """注入故障来源：CollectAgent 降级（failed），其余分支照常评估。"""
    from _daily_helpers import failing_stub

    adapter_map = {"cisa_kev": failing_stub("cisa_kev")}
    osv_adapter, _server, factory = osv_mcp_adapter()
    adapter_map["osv_mcp"] = osv_adapter

    from apps.vulntell.pipeline.daily import DailyBriefingConfig, DailyBriefingRunner

    config = DailyBriefingConfig(
        run_date=dt.date(2024, 6, 1),
        window_days=(WINDOW_END - WINDOW_START).days,
        sources=("cisa_kev", "osv_mcp"),
        osv_sample_ids=("CVE-2024-3094",),
        out_dir=tmp_path / "out",
        db=str(tmp_path / "f.sqlite3"),
    )
    runner = DailyBriefingRunner(
        config,
        adapters=adapter_map,
        http_fetch=lambda url: (_ for _ in ()).throw(RuntimeError("unused")),
        mcp_transport_factory=factory,
    )
    result = await runner.run()
    state = result.pipeline.final_state
    assert state.source_status["cisa_kev"] == "failed"
    assert "cisa_kev" in state.failed_sources
    assert state.source_status["osv_mcp"] == "ok"
    assert result.pipeline.report is not None  # 部分失败仍出报告
    assert result.pipeline.execution_report.success  # 管线整体成功（部分失败语义）
    canonical_cves = {c["cve_id"] for c in state.canonical}
    assert canonical_cves == {"CVE-2024-3094"}


# ---------------------------------------------------------------- Runner E2E


async def test_runner_outputs_all_artifacts(tmp_path):
    result, _adapters, _server = await run_offline_briefing(tmp_path)
    expected = {"dashboard.html", "report.md", "report.json", "dual_path.json"}
    assert expected <= set(result.outputs)
    for name, path in result.outputs.items():
        assert path.exists(), f"missing artifact {name}"
    html_text = (result.out_dir / "dashboard.html").read_text(encoding="utf-8")
    assert result.run_id in html_text  # run_id 在页眉
    assert "OSV 双路径一致性对照" in html_text
    assert "多智能体执行时间线" in html_text
    md = (result.out_dir / "report.md").read_text(encoding="utf-8")
    assert "canonical" in md
    dual = json.loads((result.out_dir / "dual_path.json").read_text(encoding="utf-8"))
    assert dual["summary"]["hash_equal"] == 1


async def test_runner_skips_dual_path_when_configured(tmp_path):
    from _daily_helpers import kev_stub

    adapter_map = {"cisa_kev": kev_stub()}
    osv_adapter, _server, factory = osv_mcp_adapter()
    adapter_map["osv_mcp"] = osv_adapter

    from apps.vulntell.pipeline.daily import DailyBriefingConfig, DailyBriefingRunner

    config = DailyBriefingConfig(
        run_date=dt.date(2024, 6, 1),
        window_days=(WINDOW_END - WINDOW_START).days,
        sources=("cisa_kev", "osv_mcp"),
        osv_sample_ids=("CVE-2024-3094",),
        out_dir=tmp_path / "out2",
        db=str(tmp_path / "daily2.sqlite3"),
        skip_dual_path=True,
    )
    runner = DailyBriefingRunner(
        config, adapters=adapter_map, http_fetch=None, mcp_transport_factory=factory
    )
    second = await runner.run()
    assert "dual_path.json" not in second.outputs
    assert second.dual_path is None
    html_text = (second.out_dir / "dashboard.html").read_text(encoding="utf-8")
    assert "OSV 双路径一致性对照" not in html_text


async def test_runner_store_persists_records(tmp_path):
    result, _adapters, _server = await run_offline_briefing(tmp_path)
    db_path = tmp_path / "daily.sqlite3"
    assert db_path.exists() and db_path.stat().st_size > 0
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        conn.close()
    assert tables, "sqlite store should contain at least one table"
