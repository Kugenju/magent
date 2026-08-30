"""[兼容转发] VulnTellState 已迁移至 apps.vulntell.pipeline.state（阶段 3）。

业务 State 的唯一实现位于 apps.vulntell.pipeline.state，本课程模块仅作转发，
避免重复定义。请勿在此新增业务逻辑。
"""

from __future__ import annotations

from apps.vulntell.pipeline.state import VulnTellState

__all__ = ["VulnTellState"]
