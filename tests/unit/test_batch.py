"""VulnTell 批次协议模块测试。"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.vulntell.batch.manifest import (
    BatchManifest,
    BatchStatus,
    calculate_content_hash,
    create_batch_manifest,
    load_manifest,
    save_manifest,
    validate_manifest,
    verify_content_hash,
)
from apps.vulntell.batch.importer import (
    import_batch,
    list_batches,
    validate_batch_directory,
)
from apps.vulntell.batch.merger import merge_batches
from apps.vulntell.cosv.models import COSVDocument
from apps.vulntell.cosv.serializer import serialize_cosv_to_file


class TestBatchManifest:
    """批次清单测试。"""

    def test_create_batch_manifest(self):
        """测试创建批次清单。"""
        manifest = create_batch_manifest(
            collector_id="collector-1",
            source="nvd",
            dataset_version="2024-01-01",
            window_start="2024-01-01T00:00:00Z",
            window_end="2024-01-02T00:00:00Z",
            record_count=100,
            content_hash="abc123",
        )
        assert manifest.batch_id
        assert manifest.collector_id == "collector-1"
        assert manifest.source == "nvd"
        assert manifest.status == BatchStatus.RECEIVED

    def test_validate_manifest_valid(self):
        """测试校验有效清单。"""
        manifest = create_batch_manifest(
            collector_id="collector-1",
            source="nvd",
            dataset_version="2024-01-01",
            window_start="2024-01-01T00:00:00Z",
            window_end="2024-01-02T00:00:00Z",
            record_count=100,
            content_hash="abc123",
        )
        is_valid, errors = validate_manifest(manifest)
        assert is_valid
        assert errors == []

    def test_validate_manifest_missing_fields(self):
        """测试校验缺少字段的清单。"""
        manifest = BatchManifest(
            collector_id="",
            source="",
            dataset_version="",
            window_start="",
            window_end="",
            content_hash="",
        )
        is_valid, errors = validate_manifest(manifest)
        assert not is_valid
        assert len(errors) >= 5

    def test_save_and_load_manifest(self):
        """测试保存和加载清单。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = create_batch_manifest(
                collector_id="collector-1",
                source="nvd",
                dataset_version="2024-01-01",
                window_start="2024-01-01T00:00:00Z",
                window_end="2024-01-02T00:00:00Z",
                record_count=100,
                content_hash="abc123",
            )
            save_manifest(manifest, tmpdir)
            loaded = load_manifest(tmpdir)
            assert loaded is not None
            assert loaded.batch_id == manifest.batch_id

    def test_content_hash_consistency(self):
        """测试内容哈希一致性。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            temp_path = f.name

        try:
            hash1 = calculate_content_hash(temp_path)
            hash2 = calculate_content_hash(temp_path)
            assert hash1 == hash2
        finally:
            Path(temp_path).unlink()

    def test_verify_content_hash(self):
        """测试验证内容哈希。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            temp_path = f.name

        try:
            expected_hash = calculate_content_hash(temp_path)
            assert verify_content_hash(temp_path, expected_hash)
            assert not verify_content_hash(temp_path, "wrong_hash")
        finally:
            Path(temp_path).unlink()


class TestBatchImporter:
    """批次导入器测试。"""

    def _create_test_batch(self, tmpdir: Path, batch_id: str = "test-batch") -> Path:
        """创建测试批次目录。"""
        batch_dir = tmpdir / batch_id
        batch_dir.mkdir()

        # 创建测试 COSV 文件
        doc = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
            summary="Test vulnerability",
        )
        records_path = batch_dir / "records.cosv.jsonl"
        serialize_cosv_to_file(doc, records_path, mode="w")

        # 创建 manifest
        file_hash = calculate_content_hash(records_path)
        manifest = create_batch_manifest(
            collector_id="collector-1",
            source="nvd",
            dataset_version="2024-01-01",
            window_start="2024-01-01T00:00:00Z",
            window_end="2024-01-02T00:00:00Z",
            record_count=1,
            content_hash=file_hash,
        )
        save_manifest(manifest, batch_dir)

        return batch_dir

    def test_validate_batch_directory_valid(self):
        """测试校验有效批次目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_dir = self._create_test_batch(Path(tmpdir))
            is_valid, errors = validate_batch_directory(batch_dir)
            assert is_valid
            assert errors == []

    def test_validate_batch_directory_missing_manifest(self):
        """测试校验缺少 manifest 的批次目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_dir = Path(tmpdir) / "test-batch"
            batch_dir.mkdir()
            is_valid, errors = validate_batch_directory(batch_dir)
            assert not is_valid
            assert any("manifest.json" in e for e in errors)

    def test_import_batch(self):
        """测试导入批次。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            batch_dir = self._create_test_batch(source_dir)

            target_dir = Path(tmpdir) / "target"
            target_dir.mkdir()

            result = import_batch(batch_dir, target_dir)
            assert result.success
            assert result.imported_records == 1

    def test_import_batch_idempotent(self):
        """测试幂等导入。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            batch_dir = self._create_test_batch(source_dir)

            target_dir = Path(tmpdir) / "target"
            target_dir.mkdir()

            # 第一次导入
            result1 = import_batch(batch_dir, target_dir)
            assert result1.success

            # 第二次导入（幂等）
            result2 = import_batch(batch_dir, target_dir)
            assert result2.success
            assert result2.imported_records == result1.imported_records

    def test_list_batches(self):
        """测试列出批次。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / "target"
            target_dir.mkdir()

            # 创建测试批次
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            batch_dir = self._create_test_batch(source_dir)

            # 导入
            result = import_batch(batch_dir, target_dir)
            assert result.success

            # 列出批次
            batches = list_batches(target_dir)
            assert len(batches) == 1
            assert batches[0]["source"] == "nvd"
            assert batches[0]["batch_id"] == result.manifest.batch_id


class TestBatchMerger:
    """批次合并器测试。"""

    def _create_test_batch(
        self, tmpdir: Path, batch_id: str, cve_id: str, source: str
    ) -> Path:
        """创建测试批次目录。"""
        batch_dir = tmpdir / batch_id
        batch_dir.mkdir()

        # 创建测试 COSV 文件
        doc = COSVDocument(
            id=cve_id,
            modified="2024-01-01T00:00:00Z",
            summary=f"Test vulnerability from {source}",
        )
        records_path = batch_dir / "records.cosv.jsonl"
        serialize_cosv_to_file(doc, records_path, mode="w")

        # 创建 manifest
        file_hash = calculate_content_hash(records_path)
        manifest = create_batch_manifest(
            collector_id=f"collector-{source}",
            source=source,
            dataset_version="2024-01-01",
            window_start="2024-01-01T00:00:00Z",
            window_end="2024-01-02T00:00:00Z",
            record_count=1,
            content_hash=file_hash,
        )
        save_manifest(manifest, batch_dir)

        return batch_dir

    def test_merge_batches(self):
        """测试合并批次。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()

            # 创建两个批次，共享同一个 CVE
            batch1_dir = self._create_test_batch(
                source_dir, "batch1", "CVE-2024-0001", "nvd"
            )
            batch2_dir = self._create_test_batch(
                source_dir, "batch2", "CVE-2024-0001", "osv"
            )

            output_dir = Path(tmpdir) / "output"
            merged_docs, report = merge_batches(
                [batch1_dir, batch2_dir], output_dir
            )

            assert len(merged_docs) == 1
            assert merged_docs[0].id == "CVE-2024-0001"
            assert report.merged == 1
            assert report.conflicts == 1  # 两个来源有冲突

    def test_merge_batches_with_pending(self):
        """测试合并带有 pending 的批次。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()

            # 创建一个批次，没有 CVE
            batch_dir = self._create_test_batch(
                source_dir, "batch1", "nvd:12345", "nvd"
            )

            output_dir = Path(tmpdir) / "output"
            merged_docs, report = merge_batches([batch_dir], output_dir)

            assert len(merged_docs) == 1
            assert merged_docs[0].id == "nvd:12345"
            assert report.pending == 1

    def test_merge_report_saved(self):
        """测试合并报告保存。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()

            batch_dir = self._create_test_batch(
                source_dir, "batch1", "CVE-2024-0001", "nvd"
            )

            output_dir = Path(tmpdir) / "output"
            merge_batches([batch_dir], output_dir)

            report_file = output_dir / "merge_report.json"
            assert report_file.exists()

            with open(report_file, "r", encoding="utf-8") as f:
                report = json.load(f)
            assert "merged" in report
            assert "duplicates" in report
