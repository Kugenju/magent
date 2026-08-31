"""VulnTell 批次导入器（阶段 C）。

实现目录/对象存储导入器，支持：
- 先校验 manifest/hash/schema，再原子导入
- 批次状态管理：received、validated、merged、rejected
- 失败可重试且不产生重复记录
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.vulntell.batch.manifest import (
    BatchManifest,
    BatchStatus,
    load_manifest,
    save_manifest,
    validate_manifest,
    verify_content_hash,
)
from apps.vulntell.cosv.schema import validate_cosv_file


class BatchImportResult:
    """批次导入结果。"""

    def __init__(
        self,
        success: bool,
        manifest: BatchManifest | None = None,
        errors: list[str] | None = None,
        imported_records: int = 0,
        rejected_records: int = 0,
    ):
        self.success = success
        self.manifest = manifest
        self.errors = errors or []
        self.imported_records = imported_records
        self.rejected_records = rejected_records

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "batch_id": self.manifest.batch_id if self.manifest else None,
            "errors": self.errors,
            "imported_records": self.imported_records,
            "rejected_records": self.rejected_records,
        }


def validate_batch_directory(batch_dir: str | Path) -> tuple[bool, list[str]]:
    """校验批次目录。

    Args:
        batch_dir: 批次目录路径

    Returns:
        (is_valid, errors) 元组
    """
    batch_dir = Path(batch_dir)
    errors = []

    # 检查目录是否存在
    if not batch_dir.exists():
        errors.append(f"batch directory not found: {batch_dir}")
        return False, errors

    # 检查 manifest.json 是否存在
    manifest_path = batch_dir / "manifest.json"
    if not manifest_path.exists():
        errors.append(f"manifest.json not found in {batch_dir}")
        return False, errors

    # 加载并校验 manifest
    manifest = load_manifest(batch_dir)
    if manifest is None:
        errors.append("failed to load manifest.json")
        return False, errors

    manifest_valid, manifest_errors = validate_manifest(manifest)
    if not manifest_valid:
        errors.extend(manifest_errors)
        return False, errors

    # 检查 records.cosv.jsonl 是否存在
    records_path = batch_dir / "records.cosv.jsonl"
    if not records_path.exists():
        errors.append(f"records.cosv.jsonl not found in {batch_dir}")
        return False, errors

    # 校验内容哈希
    if not verify_content_hash(records_path, manifest.content_hash):
        errors.append("content hash mismatch")
        return False, errors

    # 校验 COSV 格式
    cosv_valid, cosv_errors = validate_cosv_file(records_path)
    if not cosv_valid:
        for err in cosv_errors:
            if not err["valid"]:
                errors.append(f"line {err['line']}: {', '.join(err['errors'])}")
        return False, errors

    # 检查 quality.json 是否存在（可选）
    quality_path = batch_dir / "quality.json"
    if quality_path.exists():
        try:
            with open(quality_path, "r", encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"quality.json is invalid JSON: {e}")
            return False, errors

    return True, errors


def import_batch(
    batch_dir: str | Path,
    target_dir: str | Path,
) -> BatchImportResult:
    """导入批次到目标目录。

    Args:
        batch_dir: 源批次目录
        target_dir: 目标导入目录

    Returns:
        BatchImportResult
    """
    batch_dir = Path(batch_dir)
    target_dir = Path(target_dir)

    # 校验批次目录
    is_valid, errors = validate_batch_directory(batch_dir)
    if not is_valid:
        manifest = load_manifest(batch_dir)
        if manifest:
            manifest.status = BatchStatus.REJECTED
            save_manifest(manifest, batch_dir)
        return BatchImportResult(
            success=False,
            manifest=manifest,
            errors=errors,
        )

    # 加载 manifest
    manifest = load_manifest(batch_dir)
    if manifest is None:
        return BatchImportResult(
            success=False,
            errors=["failed to load manifest"],
        )

    # 检查是否已导入（幂等性）
    target_manifest_path = target_dir / manifest.batch_id / "manifest.json"
    if target_manifest_path.exists():
        existing_manifest = load_manifest(target_dir / manifest.batch_id)
        if existing_manifest and existing_manifest.content_hash == manifest.content_hash:
            # 已导入且哈希相同，直接返回成功
            return BatchImportResult(
                success=True,
                manifest=existing_manifest,
                imported_records=existing_manifest.record_count,
            )

    # 原子导入：先复制到临时目录，再移动到目标
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_batch_dir = Path(tmp_dir) / manifest.batch_id
            shutil.copytree(batch_dir, tmp_batch_dir)

            # 更新 manifest 状态
            manifest.status = BatchStatus.VALIDATED
            save_manifest(manifest, tmp_batch_dir)

            # 移动到目标目录
            target_batch_dir = target_dir / manifest.batch_id
            if target_batch_dir.exists():
                shutil.rmtree(target_batch_dir)
            shutil.move(str(tmp_batch_dir), str(target_batch_dir))

        # 更新 manifest 状态为 merged
        manifest.status = BatchStatus.MERGED
        save_manifest(manifest, target_batch_dir)

        return BatchImportResult(
            success=True,
            manifest=manifest,
            imported_records=manifest.record_count,
        )

    except Exception as e:
        manifest.status = BatchStatus.REJECTED
        save_manifest(manifest, batch_dir)
        return BatchImportResult(
            success=False,
            manifest=manifest,
            errors=[f"import failed: {e}"],
        )


def list_batches(target_dir: str | Path) -> list[dict[str, Any]]:
    """列出目标目录中的所有批次。

    Args:
        target_dir: 目标目录

    Returns:
        批次信息列表
    """
    target_dir = Path(target_dir)
    if not target_dir.exists():
        return []

    batches = []
    for batch_id_dir in target_dir.iterdir():
        if not batch_id_dir.is_dir():
            continue

        manifest = load_manifest(batch_id_dir)
        if manifest:
            batches.append({
                "batch_id": manifest.batch_id,
                "source": manifest.source,
                "status": manifest.status.value,
                "record_count": manifest.record_count,
                "created_at": manifest.created_at,
            })

    return batches
