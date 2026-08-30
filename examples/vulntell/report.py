"""[兼容转发] 报告组装与导出已迁移至 apps.vulntell.reporting（阶段 2）。

- ``build_report`` → apps.vulntell.reporting.report
- ``to_markdown``  → apps.vulntell.reporting.exporters

真实实现只有一份，位于 apps.vulntell.reporting；本模块仅作再导出兼容。
"""

from __future__ import annotations

from apps.vulntell.reporting.exporters import to_markdown
from apps.vulntell.reporting.report import build_report

__all__ = ["build_report", "to_markdown"]
