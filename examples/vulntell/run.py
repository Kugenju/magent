"""[兼容转发] 任务编排已迁移至 apps.vulntell.pipeline.jobs（阶段 3）。

run_vulntell 的唯一实现位于 apps.vulntell.pipeline.jobs，本课程模块仅作转发，
保留既有调用形态（examples.__main__、contract 测试、示例脚本）。请勿在此新增
业务逻辑。
"""

from __future__ import annotations

from apps.vulntell.pipeline.jobs import (
    VulnTellJobRunner,
    VulnTellRunResult,
    run_vulntell,
)

__all__ = [
    "VulnTellJobRunner",
    "VulnTellRunResult",
    "run_vulntell",
]
