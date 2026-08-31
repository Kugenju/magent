"""VulnTell 批次清单（阶段 C）。

实现 BatchManifest 数据模型和批次状态管理。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class BatchStatus(str, Enum):
    """批次状态。"""

    PENDING = "pending"
    RECEIVED = "received"
    VALIDATED = "validated"
    MERGED = "merged"
    REJECTED = "rejected"


class BatchManifest(BaseModel):
    """批次清单数据模型。

    字段：
    - batch_id: 全局唯一批次 ID
    - collector_id: 采集者标识（不含秘密）
    - source: 数据来源
    - dataset_version: 数据集版本
    - window_start: 采集窗口开始时间
    - window_end: 采集窗口结束时间
    - cosv_schema_version: COSV schema 版本
    - cosv_parser_version: COSV parser 版本
    - created_at: 创建时间
    - record_count: 记录数量
    - content_hash: 内容哈希
    - license: 许可证
    - status: 批次状态
    """

    batch_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    collector_id: str
    source: str
    dataset_version: str
    window_start: str  # RFC 3339 UTC
    window_end: str  # RFC 3339 UTC
    cosv_schema_version: str = "1.0"
    cosv_parser_version: str = "1.0"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    record_count: int = 0
    content_hash: str = ""
    license: str = "fixture-sample"
    status: BatchStatus = BatchStatus.PENDING

    def model_dump_stable(self) -> dict[str, Any]:
        """稳定序列化：保证相同输入产生相同内容哈希。"""
        return self.model_dump(
            mode="json",
            exclude_none=True,
            exclude_unset=True,
        )


def create_batch_manifest(
    collector_id: str,
    source: str,
    dataset_version: str,
    window_start: str,
    window_end: str,
    record_count: int,
    content_hash: str,
    license: str = "fixture-sample",
) -> BatchManifest:
    """创建批次清单。

    Args:
        collector_id: 采集者标识
        source: 数据来源
        dataset_version: 数据集版本
        window_start: 采集窗口开始时间（RFC 3339 UTC）
        window_end: 采集窗口结束时间（RFC 3339 UTC）
        record_count: 记录数量
        content_hash: 内容哈希
        license: 许可证

    Returns:
        BatchManifest
    """
    return BatchManifest(
        collector_id=collector_id,
        source=source,
        dataset_version=dataset_version,
        window_start=window_start,
        window_end=window_end,
        record_count=record_count,
        content_hash=content_hash,
        license=license,
        status=BatchStatus.RECEIVED,
    )


def validate_manifest(manifest: BatchManifest) -> tuple[bool, list[str]]:
    """校验批次清单。

    Args:
        manifest: 批次清单

    Returns:
        (is_valid, errors) 元组
    """
    errors = []

    # 校验必填字段
    if not manifest.batch_id:
        errors.append("batch_id is required")
    if not manifest.collector_id:
        errors.append("collector_id is required")
    if not manifest.source:
        errors.append("source is required")
    if not manifest.dataset_version:
        errors.append("dataset_version is required")
    if not manifest.window_start:
        errors.append("window_start is required")
    if not manifest.window_end:
        errors.append("window_end is required")
    if not manifest.content_hash:
        errors.append("content_hash is required")

    # 校验时间格式
    for field_name in ["window_start", "window_end", "created_at"]:
        value = getattr(manifest, field_name, None)
        if value:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{field_name} must be RFC 3339 UTC: {value}")

    # 校验 record_count
    if manifest.record_count < 0:
        errors.append("record_count must be non-negative")

    return len(errors) == 0, errors


def save_manifest(manifest: BatchManifest, batch_dir: str | Path) -> Path:
    """保存批次清单到目录。

    Args:
        manifest: 批次清单
        batch_dir: 批次目录

    Returns:
        manifest.json 文件路径
    """
    batch_dir = Path(batch_dir)
    batch_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = batch_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(), f, indent=2, ensure_ascii=False)

    return manifest_path


def load_manifest(batch_dir: str | Path) -> BatchManifest | None:
    """从目录加载批次清单。

    Args:
        batch_dir: 批次目录

    Returns:
        BatchManifest 或 None（加载失败）
    """
    batch_dir = Path(batch_dir)
    manifest_path = batch_dir / "manifest.json"

    if not manifest_path.exists():
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return BatchManifest(**data)
    except Exception:
        return None


def calculate_content_hash(file_path: str | Path) -> str:
    """计算文件内容的 SHA-256 哈希。

    Args:
        file_path: 文件路径

    Returns:
        SHA-256 哈希值
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_content_hash(file_path: str | Path, expected_hash: str) -> bool:
    """验证文件内容哈希。

    Args:
        file_path: 文件路径
        expected_hash: 期望的哈希值

    Returns:
        是否匹配
    """
    actual_hash = calculate_content_hash(file_path)
    return actual_hash == expected_hash
