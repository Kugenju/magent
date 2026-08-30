"""VulnTell 业务存储包（阶段 3 过渡占位）。

阶段 3 仅暴露 legacy 兼容层；阶段 6 将引入正式的存储实现目录。
"""

from __future__ import annotations

from apps.vulntell.storage.legacy import VulnTellStore

__all__ = ["VulnTellStore"]
