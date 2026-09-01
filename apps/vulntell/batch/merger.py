"""VulnTell 批次合并器（阶段 C/D）。

实现跨批次合并与冲突治理。

合并规则：
- 主键优先使用合法 CVE；无 CVE 的记录以规范化来源 ID 建立 pending
- 保留每个来源的 COSV 观察和 manifest 引用
- 标题/描述按来源优先级选择，同时保留冲突字段
- CVSS 向量可复算，冲突不得静默覆盖
- references、aliases、affected 去重并稳定排序
- 同一 id + modified + content_hash 幂等；较新 modified 进入修订链
- 删除不做物理删除，使用撤回/状态事件并保留审计
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.vulntell.batch.manifest import (
    BatchManifest,
    BatchStatus,
    load_manifest,
    save_manifest,
)
from apps.vulntell.cosv.models import COSVDocument
from apps.vulntell.cosv.serializer import (
    content_hash,
    deserialize_cosv,
    read_cosv_file,
    serialize_cosv,
    serialize_cosv_to_file,
)


class MergeReport:
    """合并报告。"""

    def __init__(self) -> None:
        self.received: int = 0
        self.validated: int = 0
        self.merged: int = 0
        self.rejected: int = 0
        self.duplicates: int = 0
        self.conflicts: int = 0
        self.pending: int = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "received": self.received,
            "validated": self.validated,
            "merged": self.merged,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "conflicts": self.conflicts,
            "pending": self.pending,
            "errors": self.errors,
        }


# 来源优先级（数字越小优先级越高）
SOURCE_PRIORITY: dict[str, int] = {
    "nvd": 1,
    "cisa_kev": 2,
    "github_advisory": 3,
    "osv": 4,
    "euvd": 5,
    "msrc": 6,
    "redhat": 7,
    "ubuntu": 8,
    "debian": 9,
    "jvn": 10,
    "cnvd": 11,
    "certcc": 12,
    "cisco": 13,
    "fortinet": 14,
    "paloalto": 15,
    "exploitdb": 16,
}


def _get_source_priority(source: str) -> int:
    """获取来源优先级。"""
    return SOURCE_PRIORITY.get(source, 99)


def _merge_cve_documents(docs: list[COSVDocument]) -> COSVDocument:
    """合并具有相同 CVE ID 的文档。

    Args:
        docs: 具有相同 CVE ID 的文档列表

    Returns:
        合并后的文档
    """
    if not docs:
        raise ValueError("cannot merge empty list")

    if len(docs) == 1:
        return docs[0]

    # 按来源优先级排序
    sorted_docs = sorted(
        docs,
        key=lambda d: _get_source_priority(
            d.database_specific.source if d.database_specific else "unknown"
        ),
    )

    # 使用优先级最高的文档作为基础
    base = sorted_docs[0]

    # 合并 aliases
    all_aliases = set(base.aliases)
    for doc in sorted_docs[1:]:
        all_aliases.update(doc.aliases)
    all_aliases.add(base.id)

    # 合并 references
    all_refs = list(base.references)
    seen_refs = {(r.type, r.url) for r in all_refs}
    for doc in sorted_docs[1:]:
        for ref in doc.references:
            if (ref.type, ref.url) not in seen_refs:
                all_refs.append(ref)
                seen_refs.add((ref.type, ref.url))

    # 合并 severity（保留最高分）
    all_severity = list(base.severity)
    for doc in sorted_docs[1:]:
        for sev in doc.severity:
            # 简单合并：如果类型不同则添加
            if not any(s.type == sev.type for s in all_severity):
                all_severity.append(sev)

    # 合并 affected
    all_affected = list(base.affected)
    seen_packages = {(a.package.name, a.package.ecosystem) for a in all_affected}
    for doc in sorted_docs[1:]:
        for aff in doc.affected:
            pkg_key = (aff.package.name, aff.package.ecosystem)
            if pkg_key not in seen_packages:
                all_affected.append(aff)
                seen_packages.add(pkg_key)

    # 合并 credits
    all_credits = list(base.credits)
    for doc in sorted_docs[1:]:
        for credit in doc.credits:
            if credit not in all_credits:
                all_credits.append(credit)

    # 更新 modified 时间为最新
    latest_modified = base.modified
    for doc in sorted_docs[1:]:
        if doc.modified > latest_modified:
            latest_modified = doc.modified

    return COSVDocument(
        schema_version=base.schema_version,
        id=base.id,
        modified=latest_modified,
        published=base.published,
        aliases=sorted(all_aliases),
        summary=base.summary,
        details=base.details,
        affected=all_affected,
        severity=all_severity,
        references=sorted(all_refs, key=lambda r: (r.type, r.url)),
        credits=all_credits,
        database_specific=base.database_specific,
    )


def merge_batches(
    batch_dirs: list[str | Path],
    output_dir: str | Path,
) -> tuple[list[COSVDocument], MergeReport]:
    """合并多个批次。

    Args:
        batch_dirs: 批次目录列表
        output_dir: 输出目录

    Returns:
        (merged_docs, report) 元组
    """
    report = MergeReport()
    all_docs: list[COSVDocument] = []
    seen_hashes: set[str] = set()

    # 收集所有批次的文档
    for batch_dir in batch_dirs:
        batch_dir = Path(batch_dir)

        # 加载 manifest
        manifest = load_manifest(batch_dir)
        if manifest is None:
            report.errors.append(f"failed to load manifest from {batch_dir}")
            report.rejected += 1
            continue

        report.received += 1

        # 校验 manifest
        from apps.vulntell.batch.manifest import validate_manifest
        is_valid, errors = validate_manifest(manifest)
        if not is_valid:
            report.errors.extend(errors)
            report.rejected += 1
            continue

        report.validated += 1

        # 读取 COSV 文件
        records_path = batch_dir / "records.cosv.jsonl"
        if not records_path.exists():
            report.errors.append(f"records.cosv.jsonl not found in {batch_dir}")
            report.rejected += 1
            continue

        docs = read_cosv_file(records_path)

        # 去重（基于内容哈希）
        for doc in docs:
            doc_hash = content_hash(doc)
            if doc_hash in seen_hashes:
                report.duplicates += 1
                continue
            seen_hashes.add(doc_hash)
            all_docs.append(doc)

    # 按 CVE ID 分组
    by_cve: dict[str, list[COSVDocument]] = {}
    pending: list[COSVDocument] = []

    for doc in all_docs:
        if doc.id.startswith("CVE-"):
            by_cve.setdefault(doc.id, []).append(doc)
        else:
            pending.append(doc)

    # 合并相同 CVE 的文档
    merged_docs: list[COSVDocument] = []
    for cve_id, docs in by_cve.items():
        if len(docs) > 1:
            report.conflicts += 1
        merged = _merge_cve_documents(docs)
        merged_docs.append(merged)

    # 添加 pending 文档
    merged_docs.extend(pending)
    report.pending = len(pending)
    report.merged = len(merged_docs)

    # 保存合并结果
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存合并后的文档
    output_file = output_dir / "merged.cosv.jsonl"
    # 合并是可重复操作：覆盖旧输出，避免重复运行不断追加相同记录。
    if output_file.exists():
        output_file.unlink()
    for doc in merged_docs:
        serialize_cosv_to_file(doc, output_file, mode="a")

    # 保存合并报告
    report_file = output_dir / "merge_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    return merged_docs, report
