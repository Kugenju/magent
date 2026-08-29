"""阶段 8 离线实验 CLI（Task 7）。

默认离线运行：串行基线、并行 DAG（多种并发度）、Checkpoint 恢复、可靠（重试/超时）、
VulnTell 质量评测、参考框架对比记录。结果写入 ``benchmarks/out/``（已被 .gitignore 忽略）：

- ``results.json``   机器可读（场景 + 质量 + 对比）
- ``scenarios.csv``  每场景聚合统计
- ``REPORT.md``      人工可读摘要

不联网、不调用真实 LLM、不抓取漏洞引用 URL、不使用未授权真实漏洞数据。不在仓库提交
临时数据库与缓存。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import pathlib
import time

from examples.vulntell.loading import load_dataset_meta

from .config import ExperimentConfig
from .quality import evaluate_vulntell_quality, run_pipeline
from .reference_comparison import collect_reference_comparison, to_comparison_report
from .runner import run_scenario
from .scenarios import run_parallel, run_recovery, run_reliability, run_sequential_baseline

_OUT_DIR = pathlib.Path(__file__).resolve().parent / "out"
_FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[1] / "examples" / "vulntell" / "fixtures"


async def _collect() -> dict:
    concurrency_levels = [1, 2, 4, 8]
    scenario_results: list[tuple[str, object]] = []

    cfg = ExperimentConfig(experiment_id="bench-sequential", scenario_id="sequential-baseline", concurrency=1, repetitions=5)
    scenario_results.append(("sequential-baseline", await run_scenario(cfg, run_sequential_baseline, clock=time.time)))

    for c in concurrency_levels:
        cfg = ExperimentConfig(experiment_id=f"bench-parallel-{c}", scenario_id="parallel-dag", concurrency=c, repetitions=5)
        scenario_results.append((f"parallel-dag@{c}", await run_scenario(cfg, run_parallel, clock=time.time)))

    cfg = ExperimentConfig(experiment_id="bench-recovery", scenario_id="checkpoint-recovery", checkpoint_enabled=True, repetitions=5)
    scenario_results.append(("checkpoint-recovery", await run_scenario(cfg, run_recovery, clock=time.time)))

    cfg = ExperimentConfig(experiment_id="bench-reliability", scenario_id="reliability", retry_max_attempts=3, timeout=0.001, repetitions=5)
    scenario_results.append(("reliability", await run_scenario(cfg, run_reliability, clock=time.time)))

    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    final = await run_pipeline()
    quality = evaluate_vulntell_quality(meta, final, sample_threshold=2)
    reference = to_comparison_report(collect_reference_comparison())

    scenarios_out = [{"scenario": name, **r.to_dict()} for name, r in scenario_results]
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scenarios": scenarios_out,
        "quality": quality.model_dump(),
        "reference_comparison": reference,
    }


def _write_outputs(payload: dict, out_dir: pathlib.Path = _OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "results.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    csv_path = out_dir / "scenarios.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "concurrency", "n", "mean_ms", "median_ms", "p95_ms", "min_ms", "max_ms", "all_correct"])
        for sc in payload["scenarios"]:
            s = sc["stats"]
            w.writerow([
                sc["scenario_id"],
                sc["concurrency"],
                s["n"],
                round(s["mean"], 3),
                round(s["median"], 3),
                round(s["p95"], 3),
                round(s["min"], 3),
                round(s["max"], 3),
                sc["all_correct"],
            ])

    md = [_build_markdown(payload)]
    (out_dir / "REPORT.md").write_text("\n".join(md), encoding="utf-8")


def _build_markdown(payload: dict) -> str:
    lines = ["# VulnTell / magent 阶段 8 评测报告", ""]
    lines.append(f"- 生成时间: {payload['generated_at']}")
    lines.append("")
    lines.append("## 场景聚合")
    lines.append("")
    lines.append("| 场景 | 并发 | n | 均值(ms) | 中位数(ms) | p95(ms) | 最小 | 最大 | 全部正确 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for sc in payload["scenarios"]:
        s = sc["stats"]
        lines.append(
            f"| {sc['scenario_id']} | {sc['concurrency']} | {s['n']} | {s['mean']:.3f} | "
            f"{s['median']:.3f} | {s['p95']:.3f} | {s['min']:.3f} | {s['max']:.3f} | {sc['all_correct']} |"
        )
    q = payload["quality"]
    lines += ["", "## VulnTell 质量评测", ""]
    lines.append(f"- 数据集: {q['dataset_id']}@{q['dataset_version']}，样本数: {q['sample_count']}，不足: {q['insufficient_data']}")
    lines.append(f"- 标准化存在率: {q['standardization'].get('presence_rate')}")
    lines.append(f"- 标准化有效率: {q['standardization'].get('efficiency_rate')}")
    lines.append(f"- 去重 precision/recall/F1: {q['dedupe'].get('precision')} / {q['dedupe'].get('recall')} / {q['dedupe'].get('f1')}")
    lines.append(f"- 跨源一致性: {q['cross_source_consistency']}，报告完整: {q['report_completeness']}，部分失败可用: {q['partial_failure_usable']}，指标可复现: {q['metric_reproducible']}")
    if q["notes"]:
        lines.append(f"- 备注: {'; '.join(q['notes'])}")
    rc = payload["reference_comparison"]
    lines += ["", "## 参考框架对比", ""]
    lines.append(f"- 可比: {rc['comparable']}，排名: {rc['ranking']}")
    for rec in rc["records"]:
        lines.append(f"  - {rec['framework']}: {rec['status']} ({rec['reason']})")
    lines += ["", "> 单次本地小样本结果不构成项目固定性能承诺；不可比项不排名。"]
    return "\n".join(lines)


async def main_async(out_dir: pathlib.Path = _OUT_DIR) -> int:
    import json  # local import to keep top clean

    payload = await _collect()
    _write_outputs(payload, out_dir)
    print(f"wrote results to {out_dir}")
    print(_build_markdown(payload))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="phase-8 offline benchmarks")
    parser.add_argument("--out", default=str(_OUT_DIR), help="output directory (default: benchmarks/out)")
    args = parser.parse_args()
    try:
        return asyncio.run(main_async(pathlib.Path(args.out)))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
