"""报告导出（阶段 2 从 examples.vulntell.report 的 to_markdown 抽出）。

提供人类可读 Markdown 与机器可读 JSON 两种导出，避免在入口层散落格式化代码。
导出是纯函数，不改变任何确定性字段；LLM 解释按原样附加，不修改结构化结果。
"""

from __future__ import annotations

from ..domain.models import Report


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


def to_json(report: Report, *, indent: int = 2) -> str:
    return report.model_dump_json(indent=indent)
