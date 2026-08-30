"""[兼容转发] 标准化已迁移至 apps.vulntell.domain.normalize（阶段 2）。

真实实现位于 apps.vulntell.domain.normalize；本模块仅作再导出兼容。
"""

from __future__ import annotations

from apps.vulntell.domain.normalize import normalize_record, parse_dt

__all__ = ["normalize_record", "parse_dt"]
