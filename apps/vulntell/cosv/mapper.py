"""VulnTell COSV 映射器（阶段 A）。

将 SourceObservation 转换为 COSVDocument。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.vulntell.cosv.models import (
    Affected,
    COSVDocument,
    DatabaseSpecific,
    Package,
    Reference,
    ReferenceType,
    Severity,
    SeverityType,
    VersionEvent,
    VersionRange,
)
from apps.vulntell.domain.models import SourceObservation


def _to_rfc3339_utc(dt: datetime | None) -> str | None:
    """将 datetime 转换为 RFC 3339 UTC 格式。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _extract_severity(normalized: dict[str, Any]) -> list[Severity]:
    """从 normalized_fields 提取 severity 信息。"""
    severity = []

    # The domain normalizer stores single CVSS measurements in ``cvss``.
    # Preserve them in COSV instead of silently dropping source quality data.
    cvss = normalized.get("cvss")
    if isinstance(cvss, dict) and (cvss.get("score") is not None or cvss.get("vector")):
        version = str(cvss.get("version") or "3.1")
        severity_type = SeverityType.CVSS_V31 if version.startswith("3.1") else (
            SeverityType.CVSS_V3 if version.startswith("3") else SeverityType.CVSS_V2
        )
        severity.append(Severity(
            type=severity_type,
            score=str(cvss.get("score")) if cvss.get("score") is not None else None,
            vector=cvss.get("vector"),
        ))

    # 检查 cvss3
    cvss3 = normalized.get("cvss3")
    if cvss3:
        if isinstance(cvss3, dict):
            vector = cvss3.get("vectorString") or cvss3.get("vector")
            score = str(cvss3.get("baseScore", ""))
            severity.append(Severity(type=SeverityType.CVSS_V31, score=score, vector=vector))
        elif isinstance(cvss3, str):
            severity.append(Severity(type=SeverityType.CVSS_V31, vector=cvss3))

    # 检查 cvss2
    cvss2 = normalized.get("cvss2")
    if cvss2:
        if isinstance(cvss2, dict):
            vector = cvss2.get("vectorString") or cvss2.get("vector")
            score = str(cvss2.get("baseScore", ""))
            severity.append(Severity(type=SeverityType.CVSS_V2, score=score, vector=vector))
        elif isinstance(cvss2, str):
            severity.append(Severity(type=SeverityType.CVSS_V2, vector=cvss2))

    return severity


def _extract_references(normalized: dict[str, Any]) -> list[Reference]:
    """从 normalized_fields 提取 references 信息。"""
    refs = []

    # 检查参考链接
    references = normalized.get("references", [])
    for ref in references:
        if isinstance(ref, dict):
            url = ref.get("url", "")
            ref_type = ref.get("ref_type", ref.get("type", "WEB"))
            # 映射到 COSV ReferenceType
            type_map = {
                "advisory": ReferenceType.ADVISORY,
                "web": ReferenceType.WEB,
                "fix": ReferenceType.FIX,
                "report": ReferenceType.REPORT,
                "package": ReferenceType.PACKAGE,
            }
            cosv_type = type_map.get(ref_type.lower(), ReferenceType.WEB)
            if url:
                refs.append(Reference(type=cosv_type, url=url))
        elif isinstance(ref, str) and ref.startswith("http"):
            refs.append(Reference(type=ReferenceType.WEB, url=ref))

    return refs


def _extract_affected(normalized: dict[str, Any]) -> list[Affected]:
    """从 normalized_fields 提取 affected 信息。"""
    affected = []

    # 检查受影响包
    packages = normalized.get("affected", [])
    for pkg in packages:
        if isinstance(pkg, dict):
            name = pkg.get("name", "")
            ecosystem = pkg.get("ecosystem", "unknown")
            if name:
                ranges = []
                for r in pkg.get("ranges", []):
                    if isinstance(r, dict):
                        events = []
                        for e in r.get("events", []):
                            if isinstance(e, dict):
                                events.append(VersionEvent(
                                    introduced=e.get("introduced"),
                                    fixed=e.get("fixed"),
                                    last_affected=e.get("last_affected"),
                                    limit=e.get("limit"),
                                ))
                        ranges.append(VersionRange(type=r.get("type"), events=events))

                versions = pkg.get("versions", [])
                if isinstance(versions, list):
                    versions = [str(v) for v in versions if v]
                else:
                    versions = []

                affected.append(Affected(
                    package=Package(name=name, ecosystem=ecosystem),
                    ranges=ranges,
                    versions=versions,
                ))

    return affected


def _extract_database_specific(
    obs: SourceObservation,
    normalized: dict[str, Any],
) -> DatabaseSpecific:
    """从 SourceObservation 和 normalized_fields 提取 database_specific 信息。"""
    return DatabaseSpecific(
        source=obs.source,
        source_id=obs.source_record_id,
        import_batch=normalized.get("import_batch"),
        import_sha256=normalized.get("import_sha256"),
        cnvd_level=normalized.get("cnvd_level"),
        kev_date_added=normalized.get("kev_date_added"),
        kev_due_date=normalized.get("kev_due_date"),
        kev_ransomware_use=normalized.get("kev_ransomware_use"),
        source_version_text=normalized.get("source_version_text"),
    )


def observation_to_cosv(obs: SourceObservation) -> COSVDocument:
    """将 SourceObservation 转换为 COSVDocument。

    Args:
        obs: 标准化的 SourceObservation

    Returns:
        COSVDocument
    """
    normalized = obs.normalized_fields or {}

    # 确定 ID
    cve_id = obs.cve_id
    source_record_id = obs.source_record_id

    # 优先使用 CVE，否则使用来源稳定 ID
    if cve_id and cve_id.startswith("CVE-"):
        doc_id = cve_id
    else:
        # 使用来源+记录ID作为稳定 ID
        doc_id = f"{obs.source}:{source_record_id}"

    # 构建 aliases
    aliases = []
    if cve_id and cve_id != doc_id:
        aliases.append(cve_id)

    # 提取标题和描述
    summary = normalized.get("title") or normalized.get("summary")
    details = normalized.get("description") or normalized.get("details")

    # 时间处理
    modified = _to_rfc3339_utc(obs.modified_at) or _to_rfc3339_utc(obs.observed_at)
    published = _to_rfc3339_utc(obs.published_at)

    return COSVDocument(
        schema_version="1.0",
        id=doc_id,
        modified=modified,
        published=published,
        aliases=aliases,
        summary=summary,
        details=details,
        affected=_extract_affected(normalized),
        severity=_extract_severity(normalized),
        references=_extract_references(normalized),
        credits=normalized.get("credits", []),
        database_specific=_extract_database_specific(obs, normalized),
    )


def batch_observations_to_cosv(
    observations: list[SourceObservation],
) -> tuple[list[COSVDocument], list[dict[str, Any]]]:
    """批量将 SourceObservation 转换为 COSVDocument。

    Args:
        observations: SourceObservation 列表

    Returns:
        (cosv_docs, quality_issues) 元组
    """
    cosv_docs = []
    quality_issues = []

    for obs in observations:
        try:
            doc = observation_to_cosv(obs)
            cosv_docs.append(doc)
        except Exception as e:
            quality_issues.append({
                "source": obs.source,
                "source_record_id": obs.source_record_id,
                "error": str(e),
                "type": "cosv_mapping_error",
            })

    return cosv_docs, quality_issues
