"""VulnTell 业务执行 State（阶段 3 从 examples.vulntell.state 迁移，语义不变）。

State 字段使用可序列化的 dict / list[dict] 形态，跨分支的并发写入（raw、
observations_by_source、source_status）通过 reducer 合并，避免字段冲突。

约束：State 只包含可 checkpoint 的 dict/list/标量；不放入数据库连接、adapter、
provider 或 logger。与阶段 0 baseline 的 state schema / reducers 完全一致。
"""

from __future__ import annotations

from typing import ClassVar, Optional

from pydantic import BaseModel

from apps.vulntell.domain.models import DatasetMeta


class VulnTellState(BaseModel):
    meta: DatasetMeta
    raw: dict[str, list[dict]] = {}
    observations_by_source: dict[str, list[dict]] = {}
    canonical: list[dict] = []
    pending: list[dict] = []
    quality_issues: list[dict] = []
    source_status: dict[str, str] = {}
    failed_sources: list[str] = []
    metrics: Optional[dict] = None
    report: Optional[dict] = None

    # 跨源分支写不同 key，用 reducer 合并而非覆盖
    reducers: ClassVar[dict] = {
        "raw": lambda cur, new: {**cur, **new},
        "observations_by_source": lambda cur, new: {**cur, **new},
        "source_status": lambda cur, new: {**cur, **new},
        "failed_sources": lambda cur, new: cur + new,
    }
