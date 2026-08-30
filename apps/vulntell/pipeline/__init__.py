"""VulnTell 运行时编排（阶段 3/4）。

包含业务 State、Agent、Graph 组装、任务生命周期（run/resume）和同步编排。
应用服务（apps.vulntell.application）与示例入口均通过本包获取一致的编排实现。
阶段 4 新增同步运行（SyncRunner）用于分页数据源的 checkpoint 和恢复。
"""

from __future__ import annotations

from apps.vulntell.pipeline.agents import (
    CollectAgent,
    DedupeAgent,
    EvaluateAgent,
    NormalizeAgent,
    PersistAgent,
    ReportAgent,
)
from apps.vulntell.pipeline.graph import build_vulntell_graph
from apps.vulntell.pipeline.jobs import (
    VulnTellJobRunner,
    VulnTellRunResult,
    run_vulntell,
)
from apps.vulntell.pipeline.state import VulnTellState
from apps.vulntell.pipeline.sync import SyncRunner, SyncRunnerService

__all__ = [
    "VulnTellState",
    "CollectAgent",
    "NormalizeAgent",
    "DedupeAgent",
    "PersistAgent",
    "EvaluateAgent",
    "ReportAgent",
    "build_vulntell_graph",
    "VulnTellJobRunner",
    "VulnTellRunResult",
    "run_vulntell",
    "SyncRunner",
    "SyncRunnerService",
]
