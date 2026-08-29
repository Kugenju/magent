"""跨源去重与聚合（阶段 7，Task 4）。

去重策略可解释：
- 合法 CVE ID 作为强匹配键；
- 来源记录 ID 作为来源内幂等键（由业务库唯一约束保证）；
- 无 CVE ID 的记录进入待匹配集合，不强行合并；
- 字段冲突保留各来源值，按声明的来源优先级或明确策略处理，不静默覆盖。

结果可由输入记录、匹配规则版本与 parser version 重新计算。
"""

from __future__ import annotations

from collections import defaultdict

from .models import CanonicalVulnerability, Reference, SourceObservation, utc

SOURCE_PRIORITY = {"nvd": 0, "cnvd": 1}


def _merge_cve(cve_id: str, observations: list[SourceObservation]) -> CanonicalVulnerability:
    ordered = sorted(observations, key=lambda o: SOURCE_PRIORITY.get(o.source, 99))
    title = next((o.normalized_fields.get("title") for o in ordered if o.normalized_fields.get("title")), None)
    description = next(
        (o.normalized_fields.get("description") for o in ordered if o.normalized_fields.get("description")),
        None,
    )

    published = [o.published_at for o in observations if o.published_at]
    modified = [o.modified_at for o in observations if o.modified_at]
    added = [o.source_added_at for o in observations if o.source_added_at]
    observed = [o.observed_at for o in observations if o.observed_at]

    # CVSS：取 score 最高者（保留其完整度量）
    best_cvss = None
    best_score = None
    for o in ordered:
        cv = o.normalized_fields.get("cvss")
        if cv and cv.get("score") is not None:
            if best_score is None or cv["score"] > best_score:
                best_score = cv["score"]
                best_cvss = cv

    cwe: list[str] = []
    for o in ordered:
        for item in o.normalized_fields.get("cwe", []) or []:
            if item not in cwe:
                cwe.append(item)

    affected: list[str] = []
    for o in ordered:
        for item in o.normalized_fields.get("affected", []) or []:
            if item not in affected:
                affected.append(item)

    refs: list[Reference] = []
    seen_ref: set[str] = set()
    for o in ordered:
        for r in o.normalized_fields.get("references", []) or []:
            url = r.get("url") if isinstance(r, dict) else None
            if url and url not in seen_ref:
                seen_ref.add(url)
                refs.append(Reference(url=url, ref_type=r.get("type"), verified=bool(r.get("verified"))))

    sources = [o.source for o in ordered]
    quality = []
    seen_q: set[tuple] = set()
    for o in ordered:
        for i in o.quality_issues:
            key = (i.source, i.source_record_id, i.field, i.issue_type)
            if key not in seen_q:
                seen_q.add(key)
                quality.append(i)

    return CanonicalVulnerability(
        cve_id=cve_id,
        title=title,
        description=description,
        published_at=min(published) if published else None,
        modified_at=max(modified) if modified else None,
        cvss=best_cvss,
        cwe=cwe,
        affected=affected,
        references=refs,
        sources=sources,
        source_added_at=min(added) if added else None,
        first_observed_at=min(observed) if observed else None,
        observation_count=len(observations),
        quality_issues=quality,
    )


def deduplicate(
    observations: list[SourceObservation],
) -> tuple[list[CanonicalVulnerability], list[SourceObservation]]:
    """按 CVE ID 强匹配合并为 canonical；无 CVE 记录进入 pending。"""
    by_cve: dict[str, list[SourceObservation]] = defaultdict(list)
    pending: list[SourceObservation] = []
    for o in observations:
        if o.cve_id:
            by_cve[o.cve_id].append(o)
        else:
            pending.append(o)
    canonicals = [_merge_cve(cve_id, obs_list) for cve_id, obs_list in by_cve.items()]
    return canonicals, pending
