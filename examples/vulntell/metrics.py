"""[兼容转发] 指标计算已迁移至 apps.vulntell.domain.metrics（阶段 2）。

真实实现位于 apps.vulntell.domain.metrics；本模块仅作再导出兼容。
"""

from __future__ import annotations

from apps.vulntell.domain.metrics import compute_metrics

__all__ = ["compute_metrics"]
