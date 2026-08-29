"""确定性标准化与质量问题（阶段 7，Task 3）。

``normalize_record`` 是纯函数：相同输入始终产生相同 ``SourceObservation`` 与相同
质量问题集合。缺失、无效、歧义分别产出结构化 ``QualityIssue``，绝不用默认值掩盖
“缺失”与“无效”的区别。
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from .models import (
    PARSER_VERSION,
    QualityIssue,
    RawSourceRecord,
    SourceObservation,
    utc,
)

_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")
_CWE_RE = re.compile(r"^CWE-\d+$")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def parse_dt(value: Any) -> dt.datetime | None:
    """解析 ISO 时间；失败返回 None（由调用方决定质量问题类型）。"""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return utc(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        return utc(dt.datetime.fromisoformat(text))
    except ValueError:
        return None


def _is_cve(value: Any) -> bool:
    return isinstance(value, str) and bool(_CVE_RE.match(value))


def normalize_record(raw: RawSourceRecord) -> tuple[SourceObservation, list[QualityIssue]]:
    p = raw.payload
    issues: list[QualityIssue] = []
    rid = raw.record_id
    src = raw.source

    def add(field: str, issue_type: str, severity: str, message: str) -> None:
        issues.append(
            QualityIssue(
                source=src,
                source_record_id=rid,
                cve_id=p.get("cve_id"),
                field=field,
                issue_type=issue_type,
                severity=severity,
                message=message,
            )
        )

    # CVE 编号：有则校验格式；无则允许（进入待匹配集合，不报缺失）
    cve_id = p.get("cve_id")
    if cve_id is not None and not _is_cve(cve_id):
        add("cve_id", "invalid", "medium", f"cve_id 格式非法: {cve_id!r}")

    # 标题 / 描述：缺失报 missing（low）
    title = p.get("title")
    if not title:
        add("title", "missing", "low", "title 缺失")
    description = p.get("description")
    if not description:
        add("description", "missing", "low", "description 缺失")

    # 发布 / 更新 / 来源加入时间
    published_at = parse_dt(p.get("published_at"))
    if p.get("published_at") is None:
        add("published_at", "missing", "low", "published_at 缺失")
    elif published_at is None:
        add("published_at", "invalid", "medium", f"published_at 不可解析: {p.get('published_at')!r}")

    modified_at = parse_dt(p.get("modified_at"))
    if p.get("modified_at") is None:
        add("modified_at", "missing", "low", "modified_at 缺失")
    elif modified_at is None:
        add("modified_at", "invalid", "medium", f"modified_at 不可解析: {p.get('modified_at')!r}")

    source_added_at = parse_dt(p.get("source_added_at"))
    if p.get("source_added_at") is None:
        add("source_added_at", "missing", "low", "source_added_at 缺失")

    # CVSS
    cvss = None
    if "cvss_score" in p or "cvss_vector" in p or "cvss_version" in p:
        score = p.get("cvss_score")
        if score is None:
            add("cvss_score", "missing", "medium", "cvss_score 缺失")
        elif not isinstance(score, (int, float)):
            add("cvss_score", "invalid", "medium", f"cvss_score 非数值: {score!r}")
            score = None
        cvss = {
            "version": p.get("cvss_version"),
            "vector": p.get("cvss_vector"),
            "score": score,
            "severity": p.get("severity"),
        }
    else:
        add("cvss", "missing", "medium", "缺少 CVSS 度量")

    # CWE
    cwe = p.get("cwe") or []
    if not isinstance(cwe, list):
        cwe = [cwe]
    for item in cwe:
        if not _CWE_RE.match(str(item)):
            add("cwe", "invalid", "low", f"CWE 格式非法: {item!r}")

    # 受影响产品
    affected = p.get("affected") or []
    if not isinstance(affected, list):
        affected = [affected]

    # 引用
    references = p.get("references") or []
    if not isinstance(references, list):
        references = [references]
    for ref in references:
        url = ref.get("url") if isinstance(ref, dict) else None
        if not url:
            add("references", "invalid", "low", "reference 缺少 url")
        elif not _URL_RE.match(str(url)):
            add("references", "invalid", "low", f"reference url 非法: {url!r}")

    normalized_fields = {
        "title": title,
        "description": description,
        "cvss": cvss,
        "cwe": list(cwe),
        "affected": list(affected),
        "references": [
            {"url": r.get("url"), "type": r.get("type"), "verified": bool(r.get("verified"))}
            if isinstance(r, dict)
            else {"url": str(r), "type": None, "verified": False}
            for r in references
        ],
    }

    obs = SourceObservation(
        source=src,
        source_record_id=rid,
        cve_id=cve_id if _is_cve(cve_id) else None,
        published_at=published_at,
        modified_at=modified_at,
        source_added_at=source_added_at,
        observed_at=utc(raw.observed_at),
        raw_payload_hash=raw.payload_hash,
        normalized_fields=normalized_fields,
        parser_version=PARSER_VERSION,
        quality_issues=issues,
    )
    return obs, issues
