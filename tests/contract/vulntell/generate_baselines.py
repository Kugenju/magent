"""一次性脚本：从当前入口（examples.vulntell）生成冻结基线（PHASE0_1_PLAN.md Task 0.2）。

基线是“黄金参考”，记录默认 / --no-llm / 单源失败 / resume / trace 场景的
机器可读结果。这些文件提交到仓库，供阶段 1 contract tests 比较新旧入口是否等价。

仅使用临时目录与临时 SQLite，不把运行数据库 / trace 提交到 Git（本脚本生成的
baseline_*.json 是报告快照，不含运行数据库）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from helpers import normalize_report_for_compare, parse_report_json

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_DIR = Path(__file__).resolve().parent / "baselines"
BASELINE_DIR.mkdir(parents=True, exist_ok=True)


def _run(module: str, args: list[str], cwd: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, "-m", module, *args, "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{module} {args} 退出码 {proc.returncode}\n{proc.stderr}")
    return proc.returncode, parse_report_json(proc.stdout)


def _write(name: str, obj: dict) -> None:
    path = BASELINE_DIR / name
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # 1) 默认（含 FakeProvider LLM 解释）
        _, rep = _run("examples.vulntell", [], tmp_path)
        _write("baseline_default.json", normalize_report_for_compare(rep))

        # 2) --no-llm
        _, rep = _run("examples.vulntell", ["--no-llm"], tmp_path)
        _write("baseline_no_llm.json", normalize_report_for_compare(rep))

        # 3) 单源失败（cnvd 注入故障）
        _, rep = _run("examples.vulntell", ["--faulty", "cnvd", "--no-llm"], tmp_path)
        _write("baseline_faulty_cnvd.json", normalize_report_for_compare(rep))

        # 4) resume：先完整运行（写 checkpoint），再 resume
        ckpt = tmp_path / "resume.ckpt"
        _run("examples.vulntell", ["--no-llm", f"--checkpoint={ckpt}", "--run-id=resume-run"], tmp_path)
        _, rep = _run(
            "examples.vulntell",
            ["--no-llm", f"--checkpoint={ckpt}", "--run-id=resume-run", "--resume"],
            tmp_path,
        )
        _write("baseline_resume.json", normalize_report_for_compare(rep))

        # 5) trace summary（只保留结构化统计，剥离 trace_id 等非业务字段）
        trace_prefix = tmp_path / "trace"
        _run("examples.vulntell", ["--no-llm", f"--trace={trace_prefix}"], tmp_path)
        summary = json.loads((trace_prefix.with_suffix(".summary.json")).read_text(encoding="utf-8"))
        summary.pop("trace_id", None)
        _write("baseline_trace.summary.json", summary)

    print("baselines generated.")


if __name__ == "__main__":
    main()
