"""VulnTell 数据源包（阶段 3/4/5）。

阶段 3 仅暴露 legacy 兼容层；阶段 4 引入正式的协议、分页适配器和错误分类。
阶段 5 引入真实 HTTP 适配器（NVD adapter）。
"""

from __future__ import annotations

from apps.vulntell.sources.errors import (
    SourceError,
    SourceErrorKind,
    classify_exception,
    classify_http_status,
)
from apps.vulntell.sources.fixtures import (
    FaultyPagedSource,
    PagedFixtureConfig,
    PagedFixtureSource,
)
from apps.vulntell.sources.legacy import (
    FaultySourceAdapter,
    FixtureSourceAdapter,
    HttpSourceAdapter,
    SourceAdapter,
)
from apps.vulntell.sources.nvd import NVDAdapter, NVDConfig
from apps.vulntell.sources.protocol import (
    SourcePage,
    SourceRecord,
    SourceRequest,
)

__all__ = [
    # 阶段 3 legacy 兼容
    "SourceAdapter",
    "FixtureSourceAdapter",
    "HttpSourceAdapter",
    "FaultySourceAdapter",
    # 阶段 4 协议
    "SourceRequest",
    "SourcePage",
    "SourceRecord",
    # 阶段 4 分页适配器
    "PagedFixtureSource",
    "PagedFixtureConfig",
    "FaultyPagedSource",
    # 阶段 4 错误分类
    "SourceError",
    "SourceErrorKind",
    "classify_http_status",
    "classify_exception",
    # 阶段 5 NVD adapter
    "NVDAdapter",
    "NVDConfig",
]
