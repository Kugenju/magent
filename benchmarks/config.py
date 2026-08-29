"""阶段 8 实验配置（Task 3）。

实验配置冻结数据集/窗口/版本/并发/重复次数，每次运行保存配置快照、原始观测和聚合结果。
阶段 7 的 dataset/window/parser/dedup/metric 版本作为默认数据集，任何变更必须产生新的
dataset/version，不得覆盖旧结果。
"""

from __future__ import annotations

import datetime as dt
import platform
import sys
from typing import Any

from pydantic import BaseModel, Field

from . import DATASET_VERSIONS, FRAMEWORK_VERSION


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class ExperimentConfig(BaseModel):
    """一次离线实验的固定配置快照。"""

    experiment_id: str
    scenario_id: str
    dataset_id: str = DATASET_VERSIONS["dataset_id"]
    dataset_version: str = DATASET_VERSIONS["dataset_version"]
    window_start: dt.datetime = Field(default_factory=lambda: dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc))
    window_end: dt.datetime = Field(default_factory=lambda: dt.datetime(2023, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc))
    observed_at: dt.datetime = Field(default_factory=_now)
    parser_version: str = DATASET_VERSIONS["parser_version"]
    deduplication_version: str = DATASET_VERSIONS["deduplication_version"]
    metric_version: str = DATASET_VERSIONS["metric_version"]
    framework_version: str = FRAMEWORK_VERSION
    python_version: str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    dependency_versions: dict[str, str] = Field(default_factory=dict)
    concurrency: int = 1
    timeout: float | None = None
    retry_max_attempts: int = 1
    checkpoint_enabled: bool = False
    repetitions: int = 5
    seed: int = 0
    sample_threshold: int = 2

    def environment(self) -> dict[str, Any]:
        return {
            "python_version": self.python_version,
            "platform": platform.platform(),
            "framework_version": self.framework_version,
        }
