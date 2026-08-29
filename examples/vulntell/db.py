"""VulnTell 业务持久化（阶段 7，Task 4）。

使用参数化 SQL、事务和明确唯一约束（``(source, source_record_id)``、
``cve_id``、``(dataset_id, dataset_version, window_start, window_end, metric_version)``）
保证重复导入不新增逻辑重复记录。业务库与框架 Checkpoint 分离。
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3

from .models import (
    CanonicalVulnerability,
    EvaluationRun,
    MetricSnapshot,
    QualityIssue,
    RawSourceRecord,
    SourceObservation,
    utc,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_source_records (
    source TEXT NOT NULL,
    record_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (source, record_id)
);
CREATE TABLE IF NOT EXISTS source_observations (
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    cve_id TEXT,
    published_at TEXT,
    modified_at TEXT,
    source_added_at TEXT,
    observed_at TEXT NOT NULL,
    raw_payload_hash TEXT NOT NULL,
    normalized_fields_json TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    quality_issues_json TEXT NOT NULL,
    PRIMARY KEY (source, source_record_id)
);
CREATE TABLE IF NOT EXISTS canonical_vulnerabilities (
    cve_id TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    published_at TEXT,
    modified_at TEXT,
    cvss_json TEXT,
    cwe_json TEXT,
    affected_json TEXT,
    references_json TEXT,
    sources_json TEXT,
    source_added_at TEXT,
    first_observed_at TEXT,
    observation_count INTEGER,
    quality_issues_json TEXT
);
CREATE TABLE IF NOT EXISTS quality_issues (
    source TEXT,
    source_record_id TEXT,
    cve_id TEXT,
    field TEXT,
    issue_type TEXT,
    severity TEXT,
    message TEXT,
    rule_version TEXT
);
CREATE TABLE IF NOT EXISTS metric_snapshots (
    dataset_id TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    deduplication_version TEXT NOT NULL,
    metric_version TEXT NOT NULL,
    framework_version TEXT NOT NULL,
    sample_counts_json TEXT NOT NULL,
    source_status_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    insufficient_data INTEGER NOT NULL,
    PRIMARY KEY (dataset_id, dataset_version, window_start, window_end, metric_version)
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
    run_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    framework_version TEXT NOT NULL
);
"""


def _iso(value: dt.datetime | None) -> str | None:
    return utc(value).isoformat() if value is not None else None


def _from_iso(value: str | None) -> dt.datetime | None:
    return utc(dt.datetime.fromisoformat(value)) if value else None


class VulnTellStore:
    """业务 SQLite 存储，唯一键幂等写入。"""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- raw --
    def upsert_raw(self, rec: RawSourceRecord) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO raw_source_records
                   (source, record_id, observed_at, dataset_id, dataset_version, payload_hash, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    rec.source,
                    rec.record_id,
                    _iso(rec.observed_at),
                    rec.dataset_id,
                    rec.dataset_version,
                    rec.payload_hash,
                    json.dumps(rec.payload, sort_keys=True),
                ),
            )

    # -- observation --
    def upsert_observation(self, obs: SourceObservation) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO source_observations
                   (source, source_record_id, cve_id, published_at, modified_at, source_added_at,
                    observed_at, raw_payload_hash, normalized_fields_json, parser_version, schema_version,
                    quality_issues_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    obs.source,
                    obs.source_record_id,
                    obs.cve_id,
                    _iso(obs.published_at),
                    _iso(obs.modified_at),
                    _iso(obs.source_added_at),
                    _iso(obs.observed_at),
                    obs.raw_payload_hash,
                    json.dumps(obs.normalized_fields, sort_keys=True),
                    obs.parser_version,
                    obs.schema_version,
                    json.dumps([i.model_dump() for i in obs.quality_issues], sort_keys=True),
                ),
            )

    # -- canonical --
    def upsert_canonical(self, c: CanonicalVulnerability) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO canonical_vulnerabilities
                   (cve_id, title, description, published_at, modified_at, cvss_json, cwe_json,
                    affected_json, references_json, sources_json, source_added_at, first_observed_at,
                    observation_count, quality_issues_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c.cve_id,
                    c.title,
                    c.description,
                    _iso(c.published_at),
                    _iso(c.modified_at),
                    json.dumps(c.cvss.model_dump() if c.cvss else None),
                    json.dumps(c.cwe),
                    json.dumps(c.affected),
                    json.dumps([r.model_dump() for r in c.references]),
                    json.dumps(c.sources),
                    _iso(c.source_added_at),
                    _iso(c.first_observed_at),
                    c.observation_count,
                    json.dumps([i.model_dump() for i in c.quality_issues], sort_keys=True),
                ),
            )

    def insert_quality_issues(self, issues: list[QualityIssue]) -> None:
        with self._conn:
            self._conn.executemany(
                """INSERT OR IGNORE INTO quality_issues
                   (source, source_record_id, cve_id, field, issue_type, severity, message, rule_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (i.source, i.source_record_id, i.cve_id, i.field, i.issue_type, i.severity, i.message, i.rule_version)
                    for i in issues
                ],
            )

    # -- metric / run --
    def upsert_metric(self, snap: MetricSnapshot) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO metric_snapshots
                   (dataset_id, dataset_version, window_start, window_end, observed_at, parser_version,
                    deduplication_version, metric_version, framework_version, sample_counts_json,
                    source_status_json, metrics_json, insufficient_data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snap.dataset_id,
                    snap.dataset_version,
                    _iso(snap.window_start),
                    _iso(snap.window_end),
                    _iso(snap.observed_at),
                    snap.parser_version,
                    snap.deduplication_version,
                    snap.metric_version,
                    snap.framework_version,
                    json.dumps(snap.sample_counts, sort_keys=True),
                    json.dumps(snap.source_status, sort_keys=True),
                    json.dumps(snap.metrics, sort_keys=True),
                    int(snap.insufficient_data),
                ),
            )

    def upsert_run(self, run: EvaluationRun) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO evaluation_runs
                   (run_id, dataset_id, dataset_version, window_start, window_end, started_at,
                    finished_at, status, framework_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.run_id,
                    run.dataset_id,
                    run.dataset_version,
                    _iso(run.window_start),
                    _iso(run.window_end),
                    _iso(run.started_at),
                    _iso(run.finished_at),
                    run.status,
                    run.framework_version,
                ),
            )

    # -- counts for idempotency assertions --
    def count_observations(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM source_observations").fetchone()[0]

    def count_canonical(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM canonical_vulnerabilities").fetchone()[0]

    def count_raw(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM raw_source_records").fetchone()[0]
