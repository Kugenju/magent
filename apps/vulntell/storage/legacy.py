"""VulnTell 业务存储层（阶段 3 过渡区）。

阶段 3 不复制 examples.vulntell.db 的实现，仅将其作为兼容入口集中 re-export，
供 apps.vulntell.pipeline 引用。真实存储（含事务语义、幂等回放）将在阶段 6 迁移到
apps.vulntell.storage 下，届时本文件将被替换为正式实现。
"""

from __future__ import annotations

from examples.vulntell.db import VulnTellStore

__all__ = ["VulnTellStore"]
