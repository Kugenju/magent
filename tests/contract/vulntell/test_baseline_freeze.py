"""VulnTell 阶段 0 基线冻结测试（PHASE0_1_PLAN.md Task 0.2–0.5）。

冻结当前可观察行为，确保阶段 1 迁移不改变任何确定性结果、失败语义、安全边界。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest import mock

from examples.vulntell.db import VulnTellStore
from examples.vulntell.run import run_vulntell

from helpers import (
    normalize_report_for_compare,
    parse_report_json,
    run_cli_entrypoint,
)

_BASELINE_DIR = Path(__file__).resolve().parent / "baselines"

# 不进入 Trace / 日志 / 报告的业务外敏感或原始字段关键字（小写匹配）。
_FORBIDDEN_SUBSTRINGS = (
    "raw_payload",
    "api_key",
    "apikey",
    "token",
    "cookie",
    "secret",
    "password",
)


def _load_baseline(name: str) -> dict:
    return json.loads((_BASELINE_DIR / name).read_text(encoding="utf-8"))


def _block_stdout(stdout: str) -> str:
    return stdout[stdout.find("--- JSON ---"):]


# ---- 确定性（Task 0.2 / 0.5）----


def test_default_report_is_deterministic() -> None:
    rc1, rep1 = run_cli_entrypoint("examples.vulntell", [])
    rc2, rep2 = run_cli_entrypoint("examples.vulntell", [])
    assert rc1 == 0 and rc2 == 0
    assert normalize_report_for_compare(rep1) == normalize_report_for_compare(rep2)


def test_no_llm_report_is_deterministic() -> None:
    rc1, rep1 = run_cli_entrypoint("examples.vulntell", ["--no-llm"])
    rc2, rep2 = run_cli_entrypoint("examples.vulntell", ["--no-llm"])
    assert rc1 == 0 and rc2 == 0
    assert normalize_report_for_compare(rep1) == normalize_report_for_compare(rep2)


def test_default_report_matches_frozen_baseline() -> None:
    rc, rep = run_cli_entrypoint("examples.vulntell", [])
    assert rc == 0
    assert normalize_report_for_compare(rep) == _load_baseline("baseline_default.json")


def test_no_llm_report_matches_frozen_baseline() -> None:
    rc, rep = run_cli_entrypoint("examples.vulntell", ["--no-llm"])
    assert rc == 0
    assert normalize_report_for_compare(rep) == _load_baseline("baseline_no_llm.json")


# ---- 失败边界（Task 0.4）----


def test_faulty_source_produces_partial_report() -> None:
    rc, rep = run_cli_entrypoint("examples.vulntell", ["--faulty", "cnvd", "--no-llm"])
    assert rc == 0  # 部分失败仍算成功（nvd 仍可用）
    assert rep["source_status"]["cnvd"] == "failed"
    assert rep["source_status"]["nvd"] == "ok"
    assert rep["canonical_count"] == 4
    assert rep["pending_count"] == 0
    assert rep["quality_issue_count"] == 7
    # 与冻结基线一致
    assert normalize_report_for_compare(rep) == _load_baseline("baseline_faulty_cnvd.json")


def test_unknown_source_is_rejected_early() -> None:
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "apps.vulntell", "--faulty", "made_up_source"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "未知来源" in proc.stderr


# ---- 安全边界（Task 0.4）----


def test_default_run_is_offline() -> None:
    """默认运行不得发起任何网络连接。"""
    # 先建好事件循环（其内部 socketpair 会调用 connect），再在运行期屏蔽 connect。
    loop = asyncio.new_event_loop()
    try:
        with mock.patch("socket.socket.connect", side_effect=OSError("network blocked")):
            with mock.patch(
                "socket.create_connection", side_effect=OSError("network blocked")
            ):
                result = loop.run_until_complete(run_vulntell())
    finally:
        loop.close()
    assert result.report is not None
    assert result.report.canonical_count == 5


def test_trace_is_redacted() -> None:
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        prefix = str(Path(tmp) / "t")
        proc = subprocess.run(
            [sys.executable, "-m", "examples.vulntell", "--no-llm", f"--trace={prefix}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0
        blob = ""
        for suffix in (".jsonl", ".summary.json"):
            p = Path(prefix + suffix)
            assert p.exists(), f"缺少 trace 文件 {suffix}"
            blob += p.read_text(encoding="utf-8").lower()
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in blob, f"trace 含敏感/原始字段：{forbidden}"


def test_report_has_no_sensitive_or_raw_fields() -> None:
    _, rep = run_cli_entrypoint("examples.vulntell", ["--no-llm"])
    assert "raw" not in rep
    for forbidden in ("api_key", "token", "cookie", "secret", "password"):
        assert forbidden not in rep, f"报告含敏感字段：{forbidden}"


# ---- 恢复等价（Task 0.2 / 0.5）----


def test_resume_result_matches_full_run_and_is_idempotent() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = str(tmp_path / "run.db")
        ckpt_path = str(tmp_path / "ckpt.db")
        run_id = "freeze-resume"

        full = asyncio.run(
            run_vulntell(
                db=db_path, checkpoint=ckpt_path, run_id=run_id, no_llm=True, resume=False
            )
        )
        resumed = asyncio.run(
            run_vulntell(
                db=db_path, checkpoint=ckpt_path, run_id=run_id, no_llm=True, resume=True
            )
        )

        assert normalize_report_for_compare(
            full.report.model_dump()
        ) == normalize_report_for_compare(resumed.report.model_dump())

        # 幂等：resume 不应重复提交业务副作用
        store = VulnTellStore(db_path)
        obs_after_full = store.count_observations()
        store.close()

        rerun = asyncio.run(
            run_vulntell(
                db=db_path, checkpoint=ckpt_path, run_id=run_id, no_llm=True, resume=True
            )
        )
        store = VulnTellStore(db_path)
        obs_after_resume = store.count_observations()
        store.close()

        assert obs_after_resume == obs_after_full
        assert obs_after_resume > 0
        _ = rerun  # noqa: keep reference
