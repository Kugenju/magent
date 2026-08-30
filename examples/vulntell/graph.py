"""[兼容转发] build_vulntell_graph 已迁移至 apps.vulntell.pipeline.graph（阶段 3）。

业务 Graph 组装的唯一实现位于 apps.vulntell.pipeline.graph，本课程模块仅作转发，
避免重复定义。请勿在此新增业务逻辑。
"""

from __future__ import annotations

from apps.vulntell.pipeline.graph import build_vulntell_graph

__all__ = ["build_vulntell_graph"]
