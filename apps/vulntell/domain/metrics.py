"""确定性指标计算（阶段 2 从 examples.vulntell.metrics 迁移，纯函数不变）。

所有指标都是纯函数，依赖显式输入，不读取系统时间、随机数或网络。样本不足时返回
``insufficient_data=True``，不进行任何无依据排名。相对独立性只统计“当前观测范围内的首次
观察比例”，不解释为真实原创率。
"""

from __future__ import annotations

import datetime as dt

from .models import (
    DEDUPLICATION_VERSION,
    METRIC_VERSION,
    PARSER_VERSION,
    CanonicalVulnerability,
    DatasetMeta,
    MetricSnapshot,
    QualityIssue,
    SourceObservation,
)
from .policies import MIN_SAMPLES, RELEVANCE_PROFILE, REQUIRED_FIELDS


def _delay_days(added: dt.datetime | None, published: dt.datetime | None) -> float | None:
    if added is None or published is None:
        return None
    return (added - published).total_seconds() / 86400.0


def compute_metrics(
    observations: list[SourceObservation],
    canonical: list[CanonicalVulnerability],
    pending: list[SourceObservation],
    quality_issues: list[QualityIssue],
    meta: DatasetMeta,
    source_status: dict,
    *,
    observed_at=None,
) -> MetricSnapshot:
    observed_at = observed_at or meta.window_end
    insufficient = len(canonical) < MIN_SAMPLES

    # 时效性：来源加入时间相对发布时间的延迟分布
    delays = [
        d
        for d in (
            _delay_days(o.source_added_at, o.published_at)
            for o in observations
            if o.cve_id
        )
        if d is not None
    ]
    timeliness = {
        "avg_delay_days": (sum(delays) / len(delays)) if delays else None,
        "max_delay_days": max(delays) if delays else None,
    }

    # 完整性：必需字段存在率与有效率分开
    presence: dict[str, float] = {}
    for field in REQUIRED_FIELDS:
        if field == "cvss":
            present = sum(1 for c in canonical if c.cvss is not None)
        elif field == "references":
            present = sum(1 for c in canonical if c.references)
        elif field == "cwe":
            present = sum(1 for c in canonical if c.cwe)
        else:
            present = sum(1 for c in canonical if getattr(c, field))
        presence[field] = (present / len(canonical)) if canonical else 0.0
    clean = sum(1 for c in canonical if not c.quality_issues)
    efficiency_rate = (clean / len(canonical)) if canonical else 0.0

    # 维护性：窗口内更新频率
    in_window = sum(
        1
        for c in canonical
        if c.modified_at
        and meta.window_start <= c.modified_at <= meta.window_end
    )
    maintainability_rate = (in_window / len(canonical)) if canonical else 0.0

    # 可验证性：有效引用率 + 可回溯比例（observation 均带 raw_payload_hash）
    all_refs = [r for c in canonical for r in c.references]
    verified = sum(1 for r in all_refs if r.verified)
    verifiability_rate = (verified / len(all_refs)) if all_refs else 0.0
    traceable_rate = 1.0 if observations else 0.0

    # 相关性：匹配预声明画像的受影响产品比例
    matched = 0
    for c in canonical:
        if any(any(p.startswith(a) for a in RELEVANCE_PROFILE) for p in c.affected):
            matched += 1
    relevance_rate = (matched / len(canonical)) if canonical else 0.0

    # 相对独立性：首次观察落在窗口内的比例
    first_in_window = sum(
        1
        for c in canonical
        if c.first_observed_at
        and meta.window_start <= c.first_observed_at <= meta.window_end
    )
    independence_rate = (first_in_window / len(canonical)) if canonical else 0.0

    metrics = {
        "volume": {
            "total_observations": len(observations),
            "unique_vulnerabilities": len(canonical),
            "pending_observations": len(pending),
            "updated_records": sum(1 for c in canonical if c.modified_at),
        },
        "timeliness": timeliness,
        "completeness": {"presence_rate": presence, "efficiency_rate": efficiency_rate},
        "maintainability_rate": maintainability_rate,
        "verifiability_rate": verifiability_rate,
        "traceable_rate": traceable_rate,
        "relevance_rate": relevance_rate,
        "independence_rate": independence_rate,
    }

    return MetricSnapshot(
        dataset_id=meta.dataset_id,
        dataset_version=meta.dataset_version,
        window_start=meta.window_start,
        window_end=meta.window_end,
        observed_at=observed_at,
        parser_version=PARSER_VERSION,
        deduplication_version=DEDUPLICATION_VERSION,
        metric_version=METRIC_VERSION,
        framework_version=meta.framework_version,
        sample_counts={
            "observations": len(observations),
            "canonical": len(canonical),
            "pending": len(pending),
            "quality_issues": len(quality_issues),
            "sources": {s: source_status.get(s, "unknown") for s in meta.sources},
        },
        source_status=source_status,
        metrics=metrics,
        insufficient_data=insufficient,
    )
