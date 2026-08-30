"""VulnTell 阶段 1 新旧入口 contract 测试（PHASE0_1_PLAN.md Task 1.5）。

不比较整段 Markdown 文本，而是比较解析后的结构化报告与执行状态：
- 新旧入口的 canonical / pending / quality issues / metrics / source status 必须一致；
- resume 使用相同 checkpoint 时与基线一致且不重复提交业务副作用；
- 默认命令没有网络请求；
- trace 文件可生成且不含原始漏洞文本或凭据。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from apps.vulntell.application import VulnTellApplication
from apps.vulntell.config import VulnTellConfig
from examples.vulntell.run import run_vulntell

from helpers import normalize_report_for_compare, run_cli_entrypoint

_BASELINE_DIR = Path(__file__).resolve().parent / "baselines"
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


def test_default_entrypoints_are_equivalent() -> None:
    rc_old, old = run_cli_entrypoint("examples.vulntell", [])
    rc_new, new = run_cli_entrypoint("apps.vulntell", [])
    assert rc_old == 0 and rc_new == 0
    norm_old = normalize_report_for_compare(old)
    norm_new = normalize_report_for_compare(new)
    assert norm_old == norm_new
    assert norm_new == _load_baseline("baseline_default.json")


def test_no_llm_entrypoints_are_equivalent() -> None:
    rc_old, old = run_cli_entrypoint("examples.vulntell", ["--no-llm"])
    rc_new, new = run_cli_entrypoint("apps.vulntell", ["--no-llm"])
    assert rc_old == 0 and rc_new == 0
    norm_old = normalize_report_for_compare(old)
    norm_new = normalize_report_for_compare(new)
    assert norm_old == norm_new
    assert norm_new == _load_baseline("baseline_no_llm.json")


def test_faulty_source_entrypoints_are_equivalent() -> None:
    args = ["--faulty", "cnvd", "--no-llm"]
    rc_old, old = run_cli_entrypoint("examples.vulntell", args)
    rc_new, new = run_cli_entrypoint("apps.vulntell", args)
    assert rc_old == 0 and rc_new == 0
    norm_old = normalize_report_for_compare(old)
    norm_new = normalize_report_for_compare(new)
    assert norm_old == norm_new
    assert norm_new == _load_baseline("baseline_faulty_cnvd.json")


def test_resume_result_matches_baseline() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ckpt = str(tmp_path / "ckpt.db")
        # 完整运行（写 checkpoint）
        subprocess.run(
            [
                sys.executable,
                "-m",
                "apps.vulntell",
                "--no-llm",
                f"--checkpoint={ckpt}",
                "--run-id=contract-resume",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # resume 运行
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "apps.vulntell",
                "--no-llm",
                "--json",
                f"--checkpoint={ckpt}",
                "--run-id=contract-resume",
                "--resume",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        # 提取 JSON 块
        marker = "--- JSON ---"
        idx = proc.stdout.find(marker)
        import json as _json

        report = _json.loads(proc.stdout[idx + len(marker) :].strip())
        assert normalize_report_for_compare(report) == _load_baseline("baseline_resume.json")


def test_trace_output_is_written_and_redacted() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        prefix = str(Path(tmp) / "t")
        proc = subprocess.run(
            [sys.executable, "-m", "apps.vulntell", "--no-llm", f"--trace={prefix}"],
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


def test_default_entrypoint_is_offline() -> None:
    """通过应用外壳运行时不得发起网络连接。"""
    config = VulnTellConfig(run_id="offline-app", no_llm=True)
    app = VulnTellApplication(config)
    # 先建好事件循环（其内部 socketpair 会调用 connect），再在运行期屏蔽 connect。
    loop = asyncio.new_event_loop()
    try:
        with mock.patch("socket.socket.connect", side_effect=OSError("network blocked")):
            with mock.patch(
                "socket.create_connection", side_effect=OSError("network blocked")
            ):
                result = loop.run_until_complete(app.run())
    finally:
        loop.close()
    assert result.report is not None
    assert result.report.canonical_count == 5


def test_config_rejects_empty_run_id() -> None:
    import pytest

    with pytest.raises(ValueError):
        VulnTellConfig(run_id="")


def test_config_rejects_memory_resume() -> None:
    import pytest

    with pytest.raises(ValueError):
        VulnTellConfig(checkpoint=":memory:", resume=True)
