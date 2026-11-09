"""静态 dashboard（apps.vulntell.reporting.dashboard）离线测试。

覆盖：单文件零外部引用、JSON 数据帧可解析、双路径表格与 canonical 预览、
insufficient_data 横幅。
"""

from __future__ import annotations

import json

from _daily_helpers import WINDOW_END, WINDOW_START, run_offline_briefing


async def test_dashboard_is_single_file_no_external_refs(tmp_path):
    result, _a, _s = await run_offline_briefing(tmp_path)
    html_text = (result.out_dir / "dashboard.html").read_text(encoding="utf-8")
    # 无外部资源引用（零依赖承诺）
    assert 'src="' not in html_text
    assert 'href="' not in html_text
    assert "url(" not in html_text
    # script 标签只有数据帧一个
    assert html_text.count("<script") == 1
    assert '<script type="application/json" id="vulntell-data">' in html_text


async def test_dashboard_embeds_parseable_data_frame(tmp_path):
    result, _a, _s = await run_offline_briefing(tmp_path)
    html_text = (result.out_dir / "dashboard.html").read_text(encoding="utf-8")
    start = html_text.index('id="vulntell-data">') + len('id="vulntell-data">')
    end = html_text.index("</script>", start)
    blob = json.loads(html_text[start:end])
    assert blob["run_id"] == result.run_id
    assert blob["source_status"] == {"cisa_kev": "ok", "osv_mcp": "ok"}
    assert set(blob["per_source_metrics"]) == {"cisa_kev", "osv_mcp"}
    assert blob["dual_path"] is not None
    assert blob["report"]["canonical_count"] == 2


async def test_dashboard_renders_dual_path_and_canonical(tmp_path):
    result, _a, _s = await run_offline_briefing(tmp_path)
    html_text = (result.out_dir / "dashboard.html").read_text(encoding="utf-8")
    assert "CVE-2024-3094" in html_text          # 出现在双路径表与 canonical 预览
    assert "canonical hash" in html_text.lower() or "Canonical hash" in html_text
    assert "Canonical 漏洞预览" in html_text
    # 转义加固：JSON 帧内不出现裸 </
    frame_start = html_text.index('id="vulntell-data">')
    frame_end = html_text.index("</script>", frame_start)
    assert "</" not in html_text[frame_start:frame_end]


async def test_dashboard_insufficient_banner_when_flagged(tmp_path):
    """insufficient_data=True 时展示横幅；空运行也有完整骨架（multi-agent 时间线为空表）。"""
    from apps.vulntell.domain.models import DatasetMeta, Report
    from apps.vulntell.pipeline.state import VulnTellState
    from apps.vulntell.reporting.dashboard import render_dashboard

    meta = DatasetMeta(
        dataset_id="vulntell-daily",
        dataset_version="dev",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        framework_version="test",
        sources=["cisa_kev"],
    )
    now = WINDOW_END
    report = Report(
        dataset_id="vulntell-daily",
        dataset_version="dev",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        observed_at=now,
        framework_version="test",
        parser_version="t",
        deduplication_version="t",
        metric_version="t",
        generated_at=now,
        insufficient_data=True,
    )
    state = VulnTellState(meta=meta, report=report.model_dump())

    from magent.core.executor import ExecutionReport

    exec_report = ExecutionReport(
        run_id="r", initial_state={}, final_state={}, started_at=0.0, finished_at=1.0,
        duration_ms=1000.0, steps=[],
    )
    html_text = render_dashboard(
        run_id="r", meta=meta, report=report, final_state=state,
        execution_report=exec_report, dual_path=None, source_summaries={},
    )
    assert "insufficient_data" in html_text
    assert "不进行无依据排名" in html_text
    assert "数据源状态" in html_text  # 空运行仍渲染骨架
