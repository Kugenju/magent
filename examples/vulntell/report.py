"""可追溯报告构建（阶段 7，Task 6）。

报告同时包含数据集、窗口、parser/deduplication/metric/framework 版本、失败来源、
质量告警与指标。LLM 仅追加解释文本，绝不修改任何确定性字段。
"""

from __future__ import annotations

import datetime as dt

from .models import (
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


def to_markdown(report: Report) -> str:
    lines = []
    lines.append(f"# VulnTell 报告 — {report.dataset_id}@{report.dataset_version}")
    lines.append("")
    lines.append(
        f"- 窗口: {report.window_start.isoformat()} .. {report.window_end.isoformat()}"
    )
    lines.append(f"- framework: {report.framework_version}")
    lines.append(
        f"- 版本: parser={report.parser_version} dedupe={report.deduplication_version} "
        f"metric={report.metric_version}"
    )
    lines.append(f"- 来源状态: {report.source_status}")
    lines.append(f"- canonical: {report.canonical_count}, pending: {report.pending_count}")
    lines.append(f"- 质量告警: {report.quality_issue_count}")
    if report.insufficient_data:
        lines.append("")
        lines.append("> 样本不足（insufficient_data）：不进行无依据排名。")
    lines.append("")
    lines.append("## 指标")
    for key, val in report.metrics.items():
        lines.append(f"- {key}: {val}")
    if report.llm_explanation:
        lines.append("")
        lines.append("## LLM 解释（不修改确定性结果）")
        lines.append("")
        lines.append(report.llm_explanation)
    if report.llm_failed:
        lines.append("")
        lines.append("> LLM 解释生成失败，结构化报告仍可用。")
    return "\n".join(lines)
