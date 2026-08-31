"""VulnTell 存储模块测试。"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.vulntell.batch.manifest import BatchManifest, BatchStatus, create_batch_manifest
from apps.vulntell.cosv.models import COSVDocument
from apps.vulntell.domain.models import SourceObservation
from apps.vulntell.storage.storage import VulnTellStorage


class TestVulnTellStorage:
    """VulnTellStorage 测试。"""

    def test_create_storage_in_memory(self):
        """测试创建内存存储。"""
        storage = VulnTellStorage()
        assert storage is not None
        stats = storage.get_stats()
        assert stats["cosv_records"] == 0
        storage.close()

    def test_create_storage_file(self):
        """测试创建文件存储。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = VulnTellStorage(db_path)
            assert storage is not None
            stats = storage.get_stats()
            assert stats["cosv_records"] == 0
            storage.close()

    def test_upsert_cosv(self):
        """测试插入 COSV 记录。"""
        storage = VulnTellStorage()
        doc = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
            summary="Test vulnerability",
        )
        storage.upsert_cosv(doc, batch_id="batch-1")
        stats = storage.get_stats()
        assert stats["cosv_records"] == 1
        storage.close()

    def test_get_cosv(self):
        """测试获取 COSV 记录。"""
        storage = VulnTellStorage()
        doc = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
            summary="Test vulnerability",
        )
        storage.upsert_cosv(doc)
        retrieved = storage.get_cosv("CVE-2024-0001")
        assert retrieved is not None
        assert retrieved.id == "CVE-2024-0001"
        storage.close()

    def test_list_cosv(self):
        """测试列出 COSV 记录。"""
        storage = VulnTellStorage()
        for i in range(5):
            doc = COSVDocument(
                id=f"CVE-2024-{i:04d}",
                modified="2024-01-01T00:00:00Z",
                summary=f"Test vulnerability {i}",
            )
            storage.upsert_cosv(doc)
        docs = storage.list_cosv(limit=3)
        assert len(docs) == 3
        storage.close()

    def test_upsert_manifest(self):
        """测试插入 manifest。"""
        storage = VulnTellStorage()
        manifest = create_batch_manifest(
            collector_id="collector-1",
            source="nvd",
            dataset_version="2024-01-01",
            window_start="2024-01-01T00:00:00Z",
            window_end="2024-01-02T00:00:00Z",
            record_count=100,
            content_hash="abc123",
        )
        storage.upsert_manifest(manifest)
        stats = storage.get_stats()
        assert stats["manifests"] == 1
        storage.close()

    def test_get_manifest(self):
        """测试获取 manifest。"""
        storage = VulnTellStorage()
        manifest = create_batch_manifest(
            collector_id="collector-1",
            source="nvd",
            dataset_version="2024-01-01",
            window_start="2024-01-01T00:00:00Z",
            window_end="2024-01-02T00:00:00Z",
            record_count=100,
            content_hash="abc123",
        )
        storage.upsert_manifest(manifest)
        retrieved = storage.get_manifest(manifest.batch_id)
        assert retrieved is not None
        assert retrieved.batch_id == manifest.batch_id
        storage.close()

    def test_list_manifests(self):
        """测试列出 manifests。"""
        storage = VulnTellStorage()
        for i in range(3):
            manifest = create_batch_manifest(
                collector_id=f"collector-{i}",
                source="nvd",
                dataset_version="2024-01-01",
                window_start="2024-01-01T00:00:00Z",
                window_end="2024-01-02T00:00:00Z",
                record_count=100,
                content_hash=f"hash-{i}",
            )
            storage.upsert_manifest(manifest)
        manifests = storage.list_manifests()
        assert len(manifests) == 3
        storage.close()

    def test_insert_observation(self):
        """测试插入观察记录。"""
        storage = VulnTellStorage()
        obs = SourceObservation(
            source="nvd",
            source_record_id="CVE-2024-0001",
            cve_id="CVE-2024-0001",
            observed_at=datetime.now(timezone.utc),
            raw_payload_hash="abc123",
        )
        storage.insert_observation(obs, cosv_id="CVE-2024-0001")
        stats = storage.get_stats()
        assert stats["observations"] == 1
        storage.close()

    def test_insert_merge_event(self):
        """测试插入合并事件。"""
        storage = VulnTellStorage()
        storage.insert_merge_event(
            event_type="merge",
            cosv_id="CVE-2024-0001",
            source_batch_id="batch-1",
            target_batch_id="batch-2",
            event_data={"sources": ["nvd", "osv"]},
        )
        stats = storage.get_stats()
        assert stats["merge_events"] == 1
        storage.close()

    def test_list_merge_events(self):
        """测试列出合并事件。"""
        storage = VulnTellStorage()
        for i in range(3):
            storage.insert_merge_event(
                event_type="merge",
                cosv_id=f"CVE-2024-{i:04d}",
                source_batch_id="batch-1",
            )
        events = storage.list_merge_events()
        assert len(events) == 3
        storage.close()

    def test_get_stats(self):
        """测试获取统计信息。"""
        storage = VulnTellStorage()
        stats = storage.get_stats()
        assert "cosv_records" in stats
        assert "manifests" in stats
        assert "observations" in stats
        assert "merge_events" in stats
        assert "sources" in stats
        storage.close()

    def test_context_manager(self):
        """测试上下文管理器。"""
        with VulnTellStorage() as storage:
            stats = storage.get_stats()
            assert stats["cosv_records"] == 0

    def test_upsert_cosv_idempotent(self):
        """测试 COSV 插入幂等性。"""
        storage = VulnTellStorage()
        doc1 = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
            summary="Test vulnerability 1",
        )
        doc2 = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-02T00:00:00Z",
            summary="Test vulnerability 2",
        )
        storage.upsert_cosv(doc1)
        storage.upsert_cosv(doc2)
        stats = storage.get_stats()
        assert stats["cosv_records"] == 1  # 应该只有1条记录
        retrieved = storage.get_cosv("CVE-2024-0001")
        assert retrieved.summary == "Test vulnerability 2"  # 应该被更新
        storage.close()

    def test_list_cosv_by_source(self):
        """测试按来源列出 COSV 记录。"""
        storage = VulnTellStorage()
        doc1 = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
            summary="Test vulnerability",
            database_specific={"source": "nvd"},
        )
        doc2 = COSVDocument(
            id="CVE-2024-0002",
            modified="2024-01-01T00:00:00Z",
            summary="Test vulnerability",
            database_specific={"source": "osv"},
        )
        storage.upsert_cosv(doc1)
        storage.upsert_cosv(doc2)
        docs = storage.list_cosv(source="nvd")
        assert len(docs) == 1
        storage.close()
