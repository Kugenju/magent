"""[兼容转发] 去重已迁移至 apps.vulntell.domain.dedupe（阶段 2）。

真实实现位于 apps.vulntell.domain.dedupe；本模块仅作再导出兼容。
"""

from __future__ import annotations

from apps.vulntell.domain.dedupe import deduplicate

__all__ = ["deduplicate"]
