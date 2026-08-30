"""可追溯报告构建（阶段 2 从 examples.vulntell.report 迁移，组装逻辑不变）。

报告同时包含数据集、窗口、parser/deduplication/metric/framework 版本、失败来源、
质量告警与指标。LLM 仅追加解释文本，绝不修改任何确定性字段。
"""

from __future__ import annotations

import datetime as dt

from ..domain.models import (
    CanonicalVulnerability,
    DatasetMeta,
    MetricSnapshot,
    QualityIssue,
    Report,
    SourceObservation,
    utc,
)


def build_report(
    meta: DatasetMeta,
    source_status: dict,
    canonical: list[CanonicalVulnerability],
    pending: list[SourceObservation],
    quality_issues: list[QualityIssue],
    metrics: MetricSnapshot,
    *,
    observed_at=None,
    llm_explanation: str | None = None,
    llm_failed: bool = False,
) -> Report:
    observed_at = observed_at or meta.window_end
    return Report(
        dataset_id=meta.dataset_id,
        dataset_version=meta.dataset_version,
        window_start=meta.window_start,
        window_end=meta.window_end,
        observed_at=observed_at,
        framework_version=meta.framework_version,
        parser_version=metrics.parser_version,
        deduplication_version=metrics.deduplication_version,
        metric_version=metrics.metric_version,
        source_status=source_status,
        canonical_count=len(canonical),
        pending_count=len(pending),
        quality_issue_count=len(quality_issues),
        metrics=metrics.metrics,
        insufficient_data=metrics.insufficient_data,
        llm_explanation=llm_explanation,
        llm_failed=llm_failed,
        generated_at=utc(observed_at),
    )
