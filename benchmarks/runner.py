"""阶段 8 实验运行器（Task 3）。

固定配置加载、环境快照、重复运行和原始结果保存。计时由注入的单调时钟完成，便于测试
确定性；正确性断言与性能统计分离——任何一次结果错误的运行都使场景判定为无效。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .config import ExperimentConfig
from .stats import summarize

ScenarioFn = Callable[..., Awaitable["ScenarioRun"]]


@dataclass
class ScenarioRun:
    """单次运行的原始结果。"""

    duration_ms: float
    correct: bool
    report: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    """一个场景的聚合结果（原始样本 + 统计 + 正确性）。"""

    config: ExperimentConfig
    runs: list[ScenarioRun] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    all_correct: bool = True

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.config.experiment_id,
            "scenario_id": self.config.scenario_id,
            "dataset_id": self.config.dataset_id,
            "dataset_version": self.config.dataset_version,
            "parser_version": self.config.parser_version,
            "deduplication_version": self.config.deduplication_version,
            "metric_version": self.config.metric_version,
            "framework_version": self.config.framework_version,
            "concurrency": self.config.concurrency,
            "repetitions": self.config.repetitions,
            "sample_count": len(self.runs),
            "all_correct": self.all_correct,
            "stats": self.stats,
            "raw_durations_ms": [r.duration_ms for r in self.runs],
            "raw_correct": [r.correct for r in self.runs],
            "environment": self.config.environment(),
        }


async def run_scenario(
    config: ExperimentConfig,
    scenario_fn: ScenarioFn,
    *,
    clock=None,
    rng=None,
) -> ScenarioResult:
    """重复运行 ``config.repetitions`` 次，返回聚合结果。"""
    runs: list[ScenarioRun] = []
    for _ in range(config.repetitions):
        run = await scenario_fn(config, clock=clock, rng=rng)
        runs.append(run)
    durations = [r.duration_ms for r in runs]
    return ScenarioResult(
        config=config,
        runs=runs,
        stats=summarize(durations),
        all_correct=all(r.correct for r in runs),
    )
