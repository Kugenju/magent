"""VulnTell 迁移 contract 测试共享工具（阶段 0–1）。

提供：
- ``normalize_report_for_compare``：删除运行时间、trace id 等非业务字段并稳定排序；
- ``parse_report_json``：从 CLI 的 ``--json`` 输出中提取报告 dict；
- ``run_cli_entrypoint``：通过子进程运行 ``python -m <module>`` 并解析结构化报告；
- ``run_pipeline``：在进程中直接调用旧编排函数（用于等价/恢复测试）。

比较规则（见 PHASE0_1_PLAN.md Task 0.3）：
- 指标数值、来源状态、实体数量、质量问题和版本字段必须相等；
- 列表按稳定业务键排序后比较；
- LLM explanation 单独比较，不参与确定性字段等价；
- trace id、span id、generated_at 等运行标识不参与业务等价比较；
- resume 结果必须与完整运行结果相等。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# 不参与业务等价比较的运行标识 / 非确定性字段。
_NON_BUSINESS_KEYS = {"generated_at", "observed_at", "trace_id", "span_id", "run_id"}


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return sorted((_stable(v) for v in value), key=_stable_key)
    return value


def _stable_key(v: Any) -> tuple[int, str]:
    try:
        return (0, json.dumps(v, sort_keys=True, ensure_ascii=False))
    except TypeError:
        return (1, str(v))


def normalize_report_for_compare(report: dict) -> dict:
    """删除运行时间、trace id 等非业务字段并稳定排序。

    业务等价比较只关注：数据集/窗口/版本、来源状态、实体数量、质量问题和指标。
    ``generated_at``、``observed_at`` 等运行标识被剥离；嵌套 dict/list 按稳定键排序。
    """
    if report is None:
        return None
    data = {k: v for k, v in report.items() if k not in _NON_BUSINESS_KEYS}
    return _stable(data)


def parse_report_json(cli_stdout: str) -> dict:
    """从 ``--json`` 输出里 ``--- JSON ---`` 之后提取报告 dict。

    报告 JSON 之后可能还跟有 trace 写出等提示行，因此只解码首个完整 JSON 对象。
    """
    marker = "--- JSON ---"
    idx = cli_stdout.find(marker)
    if idx == -1:
        raise AssertionError("CLI 未输出 --json 报告块")
    block = cli_stdout[idx + len(marker) :].strip()
    obj, _ = json.JSONDecoder().raw_decode(block)
    return obj


def run_cli_entrypoint(
    module: str, args: list[str], cwd: Optional[Path] = None
) -> tuple[int, dict]:
    """运行 ``python -m <module> <args> --json`` 并返回 (exit_code, report_dict)。"""
    cmd = [sys.executable, "-m", module, *args, "--json"]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        timeout=120,
    )
    report = parse_report_json(proc.stdout)
    return proc.returncode, report
