"""VulnTell 数据源包（阶段 3 过渡占位）。

阶段 3 仅暴露 legacy 兼容层；阶段 4 将引入正式的 SourceAdapter 实现目录。
"""

from __future__ import annotations

from apps.vulntell.sources.legacy import (
    FaultySourceAdapter,
    FixtureSourceAdapter,
    HttpSourceAdapter,
    SourceAdapter,
)

__all__ = [
    "SourceAdapter",
    "FixtureSourceAdapter",
    "HttpSourceAdapter",
    "FaultySourceAdapter",
]
