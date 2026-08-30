"""[兼容转发] 领域模型已迁移至 apps.vulntell.domain.models（阶段 2）。

此模块仅作兼容再导出，避免破坏既有 import 与外部示例；新阶段代码应直接
``from apps.vulntell.domain.models import ...``。真实实现只有一份，位于 apps。
"""

from __future__ import annotations

from apps.vulntell.domain.models import (
    CVSS,
    DEDUPLICATION_VERSION,
    METRIC_VERSION,
    PARSER_VERSION,
    SCHEMA_VERSION,
    CanonicalVulnerability,
    DatasetMeta,
    EvaluationRun,
    MetricSnapshot,
    QualityIssue,
    RawSourceRecord,
    Reference,
    Report,
    SourceObservation,
    utc,
)

__all__ = [
    "SCHEMA_VERSION",
    "PARSER_VERSION",
    "DEDUPLICATION_VERSION",
    "METRIC_VERSION",
    "utc",
    "QualityIssue",
    "RawSourceRecord",
    "CVSS",
    "Reference",
    "SourceObservation",
    "CanonicalVulnerability",
    "DatasetMeta",
    "MetricSnapshot",
    "EvaluationRun",
    "Report",
]
