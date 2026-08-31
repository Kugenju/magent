"""VulnTell 业务存储包（阶段 E：正式存储与回归门禁）。

将当前 `examples.vulntell.db` 过渡层替换为 `apps/vulntell/storage`：
- COSV 原文、manifest、观察、规范化实体和合并事件分表保存
- SQLite 用于本地部署，后续可替换 PostgreSQL/对象存储

存储表：
- cosv_records: COSV 原文记录
- manifests: 批次清单
- observations: SourceObservation 观察
- merge_events: 合并事件审计
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from apps.vulntell.batch.manifest import BatchManifest, BatchStatus
from apps.vulntell.cosv.models import COSVDocument
from apps.vulntell.cosv.serializer import serialize_cosv
from apps.vulntell.domain.models import SourceObservation


class VulnTellStorage:
    """VulnTell 正式存储。

    使用 SQLite 存储 COSV 记录、manifest、观察和合并事件。
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """初始化存储。

        Args:
            db_path: SQLite 数据库路径（None 使用内存数据库）
        """
        if db_path is None:
            self.db_path = ":memory:"
            self._conn = sqlite3.connect(self.db_path)
        else:
            self.db_path = str(db_path)
            self._conn = sqlite3.connect(self.db_path)

        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        """创建存储表。"""
        cursor = self._conn.cursor()

        # COSV 记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cosv_records (
                id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                modified TEXT NOT NULL,
                published TEXT,
                summary TEXT,
                details TEXT,
                content_hash TEXT NOT NULL,
                source TEXT,
                source_record_id TEXT,
                batch_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # 批次清单表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manifests (
                batch_id TEXT PRIMARY KEY,
                collector_id TEXT NOT NULL,
                source TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                cosv_schema_version TEXT NOT NULL,
                cosv_parser_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                record_count INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                license TEXT NOT NULL,
                status TEXT NOT NULL,
                imported_at TEXT
            )
        """)

        # 观察表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                cve_id TEXT,
                observed_at TEXT NOT NULL,
                raw_payload_hash TEXT NOT NULL,
                cosv_id TEXT,
                batch_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (cosv_id) REFERENCES cosv_records(id),
                FOREIGN KEY (batch_id) REFERENCES manifests(batch_id)
            )
        """)

        # 合并事件表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS merge_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                cosv_id TEXT NOT NULL,
                source_batch_id TEXT NOT NULL,
                target_batch_id TEXT,
                event_data TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (cosv_id) REFERENCES cosv_records(id),
                FOREIGN KEY (source_batch_id) REFERENCES manifests(batch_id)
            )
        """)

        self._conn.commit()

    def close(self) -> None:
        """关闭存储连接。"""
        self._conn.close()

    def __enter__(self) -> VulnTellStorage:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # COSV 记录操作

    def upsert_cosv(self, doc: COSVDocument, batch_id: str | None = None) -> None:
        """插入或更新 COSV 记录。

        Args:
            doc: COSV 文档
            batch_id: 批次 ID
        """
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        content = serialize_cosv(doc)

        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT INTO cosv_records (id, schema_version, modified, published, summary, details,
                                      content_hash, source, source_record_id, batch_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                modified = excluded.modified,
                summary = excluded.summary,
                details = excluded.details,
                content_hash = excluded.content_hash,
                batch_id = excluded.batch_id,
                updated_at = excluded.updated_at
        """, (
            doc.id,
            doc.schema_version,
            doc.modified,
            doc.published,
            doc.summary,
            doc.details,
            content,
            doc.database_specific.source if doc.database_specific else None,
            doc.database_specific.source_id if doc.database_specific else None,
            batch_id,
            now,
            now,
        ))
        self._conn.commit()

    def get_cosv(self, cosv_id: str) -> COSVDocument | None:
        """获取 COSV 记录。

        Args:
            cosv_id: COSV ID

        Returns:
            COSVDocument 或 None
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM cosv_records WHERE id = ?", (cosv_id,))
        row = cursor.fetchone()
        if row is None:
            return None

        try:
            return COSVDocument(
                id=row["id"],
                schema_version=row["schema_version"],
                modified=row["modified"],
                published=row["published"],
                summary=row["summary"],
                details=row["details"],
            )
        except Exception:
            return None

    def list_cosv(self, source: str | None = None, limit: int = 100) -> list[COSVDocument]:
        """列出 COSV 记录。

        Args:
            source: 来源过滤
            limit: 最大数量

        Returns:
            COSVDocument 列表
        """
        cursor = self._conn.cursor()
        if source:
            cursor.execute(
                "SELECT * FROM cosv_records WHERE source = ? ORDER BY modified DESC LIMIT ?",
                (source, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM cosv_records ORDER BY modified DESC LIMIT ?",
                (limit,),
            )

        docs = []
        for row in cursor.fetchall():
            try:
                doc = COSVDocument(
                    id=row["id"],
                    schema_version=row["schema_version"],
                    modified=row["modified"],
                    published=row["published"],
                    summary=row["summary"],
                    details=row["details"],
                )
                docs.append(doc)
            except Exception:
                continue

        return docs

    # Manifest 操作

    def upsert_manifest(self, manifest: BatchManifest) -> None:
        """插入或更新 manifest。

        Args:
            manifest: 批次清单
        """
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT INTO manifests (batch_id, collector_id, source, dataset_version,
                                   window_start, window_end, cosv_schema_version, cosv_parser_version,
                                   created_at, record_count, content_hash, license, status, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(batch_id) DO UPDATE SET
                status = excluded.status,
                imported_at = excluded.imported_at
        """, (
            manifest.batch_id,
            manifest.collector_id,
            manifest.source,
            manifest.dataset_version,
            manifest.window_start,
            manifest.window_end,
            manifest.cosv_schema_version,
            manifest.cosv_parser_version,
            manifest.created_at,
            manifest.record_count,
            manifest.content_hash,
            manifest.license,
            manifest.status.value,
            now if manifest.status == BatchStatus.MERGED else None,
        ))
        self._conn.commit()

    def get_manifest(self, batch_id: str) -> BatchManifest | None:
        """获取 manifest。

        Args:
            batch_id: 批次 ID

        Returns:
            BatchManifest 或 None
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM manifests WHERE batch_id = ?", (batch_id,))
        row = cursor.fetchone()
        if row is None:
            return None

        try:
            return BatchManifest(
                batch_id=row["batch_id"],
                collector_id=row["collector_id"],
                source=row["source"],
                dataset_version=row["dataset_version"],
                window_start=row["window_start"],
                window_end=row["window_end"],
                cosv_schema_version=row["cosv_schema_version"],
                cosv_parser_version=row["cosv_parser_version"],
                created_at=row["created_at"],
                record_count=row["record_count"],
                content_hash=row["content_hash"],
                license=row["license"],
                status=BatchStatus(row["status"]),
            )
        except Exception:
            return None

    def list_manifests(self, source: str | None = None, status: str | None = None) -> list[BatchManifest]:
        """列出 manifests。

        Args:
            source: 来源过滤
            status: 状态过滤

        Returns:
            BatchManifest 列表
        """
        cursor = self._conn.cursor()
        query = "SELECT * FROM manifests WHERE 1=1"
        params = []

        if source:
            query += " AND source = ?"
            params.append(source)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"
        cursor.execute(query, params)

        manifests = []
        for row in cursor.fetchall():
            try:
                manifest = BatchManifest(
                    batch_id=row["batch_id"],
                    collector_id=row["collector_id"],
                    source=row["source"],
                    dataset_version=row["dataset_version"],
                    window_start=row["window_start"],
                    window_end=row["window_end"],
                    cosv_schema_version=row["cosv_schema_version"],
                    cosv_parser_version=row["cosv_parser_version"],
                    created_at=row["created_at"],
                    record_count=row["record_count"],
                    content_hash=row["content_hash"],
                    license=row["license"],
                    status=BatchStatus(row["status"]),
                )
                manifests.append(manifest)
            except Exception:
                continue

        return manifests

    # 观察操作

    def insert_observation(self, obs: SourceObservation, cosv_id: str | None = None, batch_id: str | None = None) -> None:
        """插入观察记录。

        Args:
            obs: SourceObservation
            cosv_id: 关联的 COSV ID
            batch_id: 批次 ID
        """
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT INTO observations (source, source_record_id, cve_id, observed_at,
                                      raw_payload_hash, cosv_id, batch_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            obs.source,
            obs.source_record_id,
            obs.cve_id,
            obs.observed_at.isoformat().replace("+00:00", "Z"),
            obs.raw_payload_hash,
            cosv_id,
            batch_id,
            now,
        ))
        self._conn.commit()

    # 合并事件操作

    def insert_merge_event(
        self,
        event_type: str,
        cosv_id: str,
        source_batch_id: str,
        target_batch_id: str | None = None,
        event_data: dict | None = None,
    ) -> None:
        """插入合并事件。

        Args:
            event_type: 事件类型（merge, duplicate, conflict, pending）
            cosv_id: COSV ID
            source_batch_id: 源批次 ID
            target_batch_id: 目标批次 ID
            event_data: 事件数据
        """
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT INTO merge_events (event_type, cosv_id, source_batch_id, target_batch_id,
                                      event_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            event_type,
            cosv_id,
            source_batch_id,
            target_batch_id,
            json.dumps(event_data) if event_data else None,
            now,
        ))
        self._conn.commit()

    def list_merge_events(self, cosv_id: str | None = None) -> list[dict[str, Any]]:
        """列出合并事件。

        Args:
            cosv_id: COSV ID 过滤

        Returns:
            事件列表
        """
        cursor = self._conn.cursor()
        if cosv_id:
            cursor.execute(
                "SELECT * FROM merge_events WHERE cosv_id = ? ORDER BY created_at DESC",
                (cosv_id,),
            )
        else:
            cursor.execute("SELECT * FROM merge_events ORDER BY created_at DESC")

        events = []
        for row in cursor.fetchall():
            events.append({
                "id": row["id"],
                "event_type": row["event_type"],
                "cosv_id": row["cosv_id"],
                "source_batch_id": row["source_batch_id"],
                "target_batch_id": row["target_batch_id"],
                "event_data": json.loads(row["event_data"]) if row["event_data"] else None,
                "created_at": row["created_at"],
            })

        return events

    # 统计

    def get_stats(self) -> dict[str, Any]:
        """获取存储统计信息。

        Returns:
            统计信息字典
        """
        cursor = self._conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM cosv_records")
        cosv_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM manifests")
        manifest_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM observations")
        observation_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM merge_events")
        merge_event_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(DISTINCT source) as count FROM cosv_records")
        source_count = cursor.fetchone()["count"]

        return {
            "cosv_records": cosv_count,
            "manifests": manifest_count,
            "observations": observation_count,
            "merge_events": merge_event_count,
            "sources": source_count,
        }


# 全局存储实例
_storage: VulnTellStorage | None = None


def get_storage(db_path: str | Path | None = None) -> VulnTellStorage:
    """获取全局存储实例。

    Args:
        db_path: 数据库路径（仅首次调用有效）

    Returns:
        VulnTellStorage 实例
    """
    global _storage
    if _storage is None:
        _storage = VulnTellStorage(db_path)
    return _storage


def close_storage() -> None:
    """关闭全局存储实例。"""
    global _storage
    if _storage is not None:
        _storage.close()
        _storage = None
