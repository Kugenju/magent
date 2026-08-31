"""VulnTell 业务存储包（阶段 E：正式存储与回归门禁）。

将当前 `examples.vulntell.db` 过渡层替换为 `apps/vulntell/storage`：
- COSV 原文、manifest、观察、规范化实体和合并事件分表保存
- SQLite 用于本地部署，后续可替换 PostgreSQL/对象存储
"""

from __future__ import annotations

from apps.vulntell.storage.legacy import VulnTellStore
from apps.vulntell.storage.storage import (
    VulnTellStorage,
    close_storage,
    get_storage,
)

__all__ = [
    "VulnTellStore",
    "VulnTellStorage",
    "get_storage",
    "close_storage",
]
