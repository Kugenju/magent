"""[兼容转发] 数据集 / fixture 加载已迁移至 apps.vulntell.domain.schemas（阶段 2）。

真实实现位于 apps.vulntell.domain.schemas；本模块仅作再导出兼容。
"""

from __future__ import annotations

from apps.vulntell.domain.schemas import load_dataset_meta, load_fixture

__all__ = ["load_dataset_meta", "load_fixture"]
