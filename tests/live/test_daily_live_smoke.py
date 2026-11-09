"""Daily briefing live smoke — REAL CISA KEV feed + REAL stdio MCP server.

Opt-in only:
    MAGENT_RUN_LIVE=1 pytest tests/live -q

Without the env var every test here SKIPS. This exercises the full daily
workflow with real network sources: KEV (keyless REST) + cc OSV MCP server
spawned real (official SDK), then the dual-path consistency probe against
the same OSV endpoint (direct HTTP GET vs protocol tool call).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = ROOT / "tools" / "mcp_example_server.py"
SAMPLE_IDS = ("CVE-2024-3094",)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("MAGENT_RUN_LIVE"),
        reason="live tests need MAGENT_RUN_LIVE=1 (offline CI gate stays closed)",
    ),
]
pytest.importorskip("httpx", reason="live KEV fetch uses the `net` extra")
pytest.importorskip("mcp", reason="official MCP SDK (extra `magent[mcp]`) not installed")


async def test_daily_briefing_live(tmp_path):
    from apps.vulntell.pipeline.daily import DailyBriefingConfig, DailyBriefingRunner

    config = DailyBriefingConfig(
        window_days=45,               # 保证 KEV 窗口内有真实新条目
        sources=("cisa_kev", "osv_mcp"),
        osv_sample_ids=SAMPLE_IDS,
        max_kev_records=50,           # 受控批次：烟测不拖全目录
        out_dir=tmp_path / "out",
        db=str(tmp_path / "daily.sqlite3"),
        skip_dual_path=False,
    )
    runner = DailyBriefingRunner(config)
    result = await runner.run()

    # 产物齐全（live 有 dual_path.json）
    expected = {"dashboard.html", "report.md", "report.json", "dual_path.json"}
    assert expected <= set(result.outputs), f"missing artifacts: {expected - set(result.outputs)}"
    for path in result.outputs.values():
        assert path.exists()

    # 图执行成功（来源失败不致命，但要记录状态）
    state = result.pipeline.final_state
    exec_report = result.pipeline.execution_report
    assert exec_report.success, f"pipeline failed: {state.source_status}"

    # KEV 真实采集：允许环境无外网时的诚实降级，但断言状态被如实记录
    status = state.source_status
    assert status.get("cisa_kev") in {"ok", "failed"}
    if status.get("cisa_kev") == "ok":
        assert len(state.observations_by_source.get("cisa_kev", [])) > 0
        assert result.source_summaries["cisa_kev"]["fetched"] > 0

    # MCP 路径真实往返（失败也需要被如实记录而不是消失）
    summary = result.source_summaries.get("osv_mcp", {})
    assert summary.get("requested") == len(SAMPLE_IDS)

    # 双路径对照：REST 与 MCP 对同一端点同形成功/同形失败
    dual = json.loads((result.out_dir / "dual_path.json").read_text(encoding="utf-8"))
    assert dual["summary"]["sample_size"] == len(SAMPLE_IDS)
    row = dual["rows"][0]
    assert row["rest_ok"] == row["mcp_ok"], f"paths diverge: {row}"
    if row["rest_ok"]:
        assert row["payload_hash_equal"] is True
        assert row["fields_equal"] is True

    html_text = (result.out_dir / "dashboard.html").read_text(encoding="utf-8")
    assert "多智能体执行时间线" in html_text
    assert "OSV 双路径一致性对照" in html_text
