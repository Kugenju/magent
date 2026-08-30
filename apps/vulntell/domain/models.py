"""VulnTell 领域模型（阶段 2 从 examples.vulntell.models 迁移，业务语义不变）。

三层对象：
- ``RawSourceRecord``   来源原始载荷（保留 hash / source / record_id / observed_at）
- ``SourceObservation`` 某来源对某漏洞的标准化观察
- ``CanonicalVulnerability`` 跨来源归并后的漏洞实体

以及质量告警、指标快照、评估运行和报告模型。所有时间统一为 UTC。

序列化：框架 checkpoint 用 ``json.dumps(state.model_dump())`` 持久化，因此本模块
所有模型在 ``model_dump`` 时把 ``datetime`` 统一转为 ISO 字符串（纯业务侧处理，
不修改 magent 核心）。实例属性仍为 ``datetime``，逻辑代码不受影响。

约束：本模块不导入 magent 内部实现，保持可独立导入、无网络与框架副作用。
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from pydantic import BaseModel, Field, model_serializer

SCHEMA_VERSION = "1"
PARSER_VERSION = "1"
DEDUPLICATION_VERSION = "1"
METRIC_VERSION = "1"


def utc(value: dt.datetime) -> dt.datetime:
    """归一化到 UTC；naive 时间按 UTC 处理。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _ser_value(v: Any) -> Any:
    if isinstance(v, dt.datetime):
        return v.isoformat()
    if isinstance(v, BaseModel):
        return v.model_dump()
    if isinstance(v, list):
        return [_ser_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _ser_value(val) for k, val in v.items()}
    return v


class _VTBase(BaseModel):
    """基类：model_dump 时递归把 datetime 转为 ISO 字符串，保证 checkpoint 可序列化。"""

    @model_serializer(mode="plain")
    def _vt_serialize(self) -> dict:
        return {name: _ser_value(getattr(self, name)) for name in type(self).model_fields}


class QualityIssue(_VTBase):
    """结构化的数据质量问题，区分 missing / invalid / ambiguous。"""

    source: str
    source_record_id: Optional[str] = None
    cve_id: Optional[str] = None
    field: str
    issue_type: str  # missing | invalid | ambiguous
    severity: str = "medium"  # low | medium | high
    message: str = ""
    rule_version: str = PARSER_VERSION


class RawSourceRecord(_VTBase):
    """来源原始载荷。payload 不进框架 State 的归一化字段，只存引用与 hash。"""

    source: str
    record_id: str
    observed_at: dt.datetime
    dataset_id: str
    dataset_version: str
    payload: dict
    payload_hash: str
    parser_version: str = PARSER_VERSION
    schema_version: str = SCHEMA_VERSION


class CVSS(_VTBase):
    version: str
    vector: Optional[str] = None
    score: Optional[float] = None
    severity: Optional[str] = None


class Reference(_VTBase):
    url: str
    ref_type: Optional[str] = None
    verified: bool = False


class SourceObservation(_VTBase):
    """某来源对某漏洞的标准化观察。"""

    source: str
    source_record_id: str
    cve_id: Optional[str] = None
    published_at: Optional[dt.datetime] = None
    modified_at: Optional[dt.datetime] = None
    source_added_at: Optional[dt.datetime] = None
    observed_at: dt.datetime
    raw_payload_hash: str
    raw_payload_ref: Optional[str] = None
    normalized_fields: dict = Field(default_factory=dict)
    parser_version: str = PARSER_VERSION
    schema_version: str = SCHEMA_VERSION
    quality_issues: list[QualityIssue] = Field(default_factory=list)


class CanonicalVulnerability(_VTBase):
    """跨来源归并后的漏洞实体（仅由有 CVE ID 的记录合并而来）。"""

    cve_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    published_at: Optional[dt.datetime] = None
    modified_at: Optional[dt.datetime] = None
    cvss: Optional[CVSS] = None
    cwe: list[str] = Field(default_factory=list)
    affected: list[str] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    source_added_at: Optional[dt.datetime] = None
    first_observed_at: Optional[dt.datetime] = None
    observation_count: int = 0
    quality_issues: list[QualityIssue] = Field(default_factory=list)


class DatasetMeta(_VTBase):
    """冻结的数据集/窗口/版本边界。"""

    dataset_id: str
    dataset_version: str
    window_start: dt.datetime
    window_end: dt.datetime
    parser_version: str = PARSER_VERSION
    deduplication_version: str = DEDUPLICATION_VERSION
    metric_version: str = METRIC_VERSION
    framework_version: str
    license: str = "fixture-sample"
    sources: list[str] = Field(default_factory=list)


class MetricSnapshot(_VTBase):
    """一次评估的指标快照，纯结构化、可重放。"""

    dataset_id: str
    dataset_version: str
    window_start: dt.datetime
    window_end: dt.datetime
    observed_at: dt.datetime
    parser_version: str = PARSER_VERSION
    deduplication_version: str = DEDUPLICATION_VERSION
    metric_version: str = METRIC_VERSION
    framework_version: str
    sample_counts: dict = Field(default_factory=dict)
    source_status: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    insufficient_data: bool = False


class EvaluationRun(_VTBase):
    run_id: str
    dataset_id: str
    dataset_version: str
    window_start: dt.datetime
    window_end: dt.datetime
    started_at: dt.datetime
    finished_at: Optional[dt.datetime] = None
    status: str = "running"  # success | partial | failed
    framework_version: str


class Report(_VTBase):
    """最终可追溯报告，必须包含数据集/窗口/各版本/失败来源/质量告警。"""

    dataset_id: str
    dataset_version: str
    window_start: dt.datetime
    window_end: dt.datetime
    observed_at: dt.datetime
    framework_version: str
    parser_version: str
    deduplication_version: str
    metric_version: str
    source_status: dict = Field(default_factory=dict)
    canonical_count: int = 0
    pending_count: int = 0
    quality_issue_count: int = 0
    metrics: dict = Field(default_factory=dict)
    insufficient_data: bool = False
    llm_explanation: Optional[str] = None
    llm_failed: bool = False
    generated_at: dt.datetime
