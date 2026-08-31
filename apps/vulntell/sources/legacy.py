"""VulnTell 数据源适配层（阶段 3/4 过渡区）。

阶段 3 将 examples.vulntell.sources 作为兼容入口集中 re-export。
阶段 4 引入了正式的 protocol.py、fixtures.py 和 errors.py。
阶段 5 已引入独立真实 HTTP adapter（`nvd.py`、`cisa_kev.py`、`cnvd.py`）；本文件仍为旧
`SourceAdapter` 兼容层，待 live pipeline 与阶段 6 存储迁移完成后替换。

替换条件：
- apps.vulntell.sources.protocol.SourceRequest/SourcePage 已稳定
- apps.vulntell.sources.fixtures.PagedFixtureSource 已验证所有分页场景
- apps.vulntell.sources.errors.SourceError 已覆盖所有错误类型

删除版本：v2.0.0 (预计阶段 5 完成后)

迁移路径：
- 新代码使用 apps.vulntell.sources.PagedFixtureSource（阶段 4+）
- 旧代码继续使用 apps.vulntell.sources.FixtureSourceAdapter（兼容期）
- 阶段 6 删除本文件和 examples.vulntell.sources
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
