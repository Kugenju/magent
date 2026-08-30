"""VulnTell 数据源适配层（阶段 3 过渡区）。

阶段 3 不复制 examples.vulntell.sources 的实现，仅将其作为兼容入口集中 re-export，
供 apps.vulntell.pipeline 引用。真实数据源（含 HTTP adapter）将在阶段 4 迁移到
apps.vulntell.sources 下，届时本文件将被替换为正式实现。
"""

from __future__ import annotations

from examples.vulntell.sources import (
    FixtureSourceAdapter,
    FaultySourceAdapter,
    HttpSourceAdapter,
    SourceAdapter,
)

__all__ = [
    "SourceAdapter",
    "FixtureSourceAdapter",
    "HttpSourceAdapter",
    "FaultySourceAdapter",
]
