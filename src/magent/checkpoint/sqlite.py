"""SQLite checkpoint store (phase 5, §5).

Single-writer, file-backed store. All blocking SQL runs in a thread executor so
the Agent event loop is never stalled. ``checkpoints`` stores JSON text only —
no pickle — and every append is transactional; a crash mid-write leaves either
a full row or none, never a half-written checkpoint.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time

from .errors import CheckpointConflictError, CheckpointError
from .models import CheckpointRecord, EffectRecord, RunRecord, SCHEMA_VERSION


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    workflow_version TEXT NOT NULL,
    state_type TEXT NOT NULL,
    state_schema_hash TEXT NOT NULL,
    initial_state_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    run_id TEXT NOT NULL,
    checkpoint_seq INTEGER NOT NULL,
    phase TEXT NOT NULL,
    node_id TEXT,
    node_version TEXT,
    attempt INTEGER,
    input_state_json TEXT,
    output_state_json TEXT,
    updates_json TEXT,
    frontier_json TEXT,
    route_json TEXT,
    activated_json TEXT,
    attempts_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (run_id, checkpoint_seq)
);

CREATE TABLE IF NOT EXISTS effects (
    execution_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    node_version TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def _dump(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _load(value):
    return None if value is None else json.loads(value)


class SqliteCheckpointStore:
    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        self._closed = False

    # -- helpers ---------------------------------------------------------
    def _run(self, fn):
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, fn)

    def _row_to_checkpoint(self, row) -> CheckpointRecord:
        rec = CheckpointRecord(
            schema_version=SCHEMA_VERSION,
            run_id=row[0],
            workflow_id="",
            workflow_version="",
            state_type="",
            state_schema_hash="",
            node_id=row[3],
            node_version=row[4],
            checkpoint_seq=row[1],
            phase=row[2],
            attempt=row[5],
            input_state=_load(row[6]),
            output_state=_load(row[7]),
            updates=_load(row[8]),
            frontier=_load(row[9]),
            route=_load(row[10]),
            activated_nodes=_load(row[11]),
            attempts=_load(row[12]) or [],
            checksum=row[13],
            created_at=row[14],
        )
        return rec

    def _verify_checksum(self, rec: CheckpointRecord) -> None:
        # Gate 1: recompute & verify checksum after the run-derived fields
        # (state_type / state_schema_hash) have been filled in.
        if rec.compute_checksum() != rec.checksum:
            raise CheckpointError(
                f"checkpoint {rec.run_id!r} seq {rec.checkpoint_seq} failed checksum "
                f"verification (possible corruption)",
                field="checksum",
                expected=rec.compute_checksum(),
                actual=rec.checksum,
            )

    def _fill_workflow(self, cp: CheckpointRecord) -> None:
        cur = self._conn.execute(
            "SELECT workflow_id, workflow_version, state_type, state_schema_hash "
            "FROM runs WHERE run_id = ?",
            (cp.run_id,),
        )
        row = cur.fetchone()
        if row is not None:
            cp.workflow_id = row[0]
            cp.workflow_version = row[1]
            cp.state_type = row[2]
            cp.state_schema_hash = row[3]

    # -- async contract --------------------------------------------------
    async def create_run(self, run: RunRecord) -> None:
        await self._run(lambda: self._create_run(run))

    def _create_run(self, run: RunRecord) -> None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (run.run_id,)
            )
            if cur.fetchone() is not None:
                raise CheckpointConflictError(
                    f"run {run.run_id!r} already exists",
                    field="run_id",
                    expected="absent",
                    actual=run.run_id,
                )
            self._conn.execute(
                "INSERT INTO runs (run_id, workflow_id, workflow_version, state_type, "
                "state_schema_hash, initial_state_json, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    run.workflow_id,
                    run.workflow_version,
                    run.state_type,
                    run.state_schema_hash,
                    _dump(run.initial_state),
                    run.status,
                    run.created_at,
                    run.updated_at,
                ),
            )
            self._conn.commit()

    async def append(self, checkpoint: CheckpointRecord) -> None:
        await self._run(lambda: self._append(checkpoint))

    def _append(self, checkpoint: CheckpointRecord) -> None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT checksum FROM checkpoints WHERE run_id = ? AND checkpoint_seq = ?",
                (checkpoint.run_id, checkpoint.checkpoint_seq),
            )
            row = cur.fetchone()
            if row is not None:
                if row[0] == checkpoint.checksum:
                    return
                raise CheckpointConflictError(
                    f"checkpoint seq {checkpoint.checkpoint_seq} for run "
                    f"{checkpoint.run_id!r} already exists with different content",
                    field="checkpoint_seq",
                    expected=row[0],
                    actual=checkpoint.checksum,
                )
            wcur = self._conn.execute(
                "SELECT workflow_id, workflow_version FROM runs WHERE run_id = ?",
                (checkpoint.run_id,),
            )
            wrow = wcur.fetchone()
            if wrow is None:
                raise CheckpointError(
                    f"cannot append checkpoint for unknown run {checkpoint.run_id!r}",
                    field="run_id",
                    actual=checkpoint.run_id,
                )
            self._conn.execute(
                "INSERT INTO checkpoints (run_id, checkpoint_seq, phase, node_id, "
                "node_version, attempt, input_state_json, output_state_json, updates_json, "
                "frontier_json, route_json, activated_json, attempts_json, checksum, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    checkpoint.run_id,
                    checkpoint.checkpoint_seq,
                    checkpoint.phase.value,
                    checkpoint.node_id,
                    checkpoint.node_version,
                    checkpoint.attempt,
                    _dump(checkpoint.input_state),
                    _dump(checkpoint.output_state),
                    _dump(checkpoint.updates),
                    _dump(checkpoint.frontier),
                    _dump(checkpoint.route),
                    _dump(checkpoint.activated_nodes),
                    _dump(checkpoint.attempts),
                    checkpoint.checksum,
                    checkpoint.created_at,
                ),
            )
            self._conn.commit()

    async def latest(self, run_id: str) -> CheckpointRecord | None:
        return await self._run(lambda: self._latest(run_id))

    def _latest(self, run_id: str) -> CheckpointRecord | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id, checkpoint_seq, phase, node_id, node_version, attempt, "
                "input_state_json, output_state_json, updates_json, frontier_json, "
                "route_json, activated_json, attempts_json, checksum, created_at "
                "FROM checkpoints WHERE run_id = ? ORDER BY checkpoint_seq DESC LIMIT 1",
                (run_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cp = self._row_to_checkpoint(row)
            self._fill_workflow(cp)
            self._verify_checksum(cp)
            return cp

    async def load_run(self, run_id: str) -> RunRecord:
        return await self._run(lambda: self._load_run(run_id))

    def _load_run(self, run_id: str) -> RunRecord:
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id, workflow_id, workflow_version, state_type, "
                "state_schema_hash, initial_state_json, status, created_at, updated_at "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise CheckpointError(
                    f"run {run_id!r} not found", field="run_id", actual=run_id
                )
            return RunRecord(
                run_id=row[0],
                workflow_id=row[1],
                workflow_version=row[2],
                state_type=row[3],
                state_schema_hash=row[4],
                initial_state=_load(row[5]),
                status=row[6],
                created_at=row[7],
                updated_at=row[8],
            )

    async def list_checkpoints(self, run_id: str) -> list[CheckpointRecord]:
        return await self._run(lambda: self._list_checkpoints(run_id))

    def _list_checkpoints(self, run_id: str) -> list[CheckpointRecord]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id, checkpoint_seq, phase, node_id, node_version, attempt, "
                "input_state_json, output_state_json, updates_json, frontier_json, "
                "route_json, activated_json, attempts_json, checksum, created_at "
                "FROM checkpoints WHERE run_id = ? ORDER BY checkpoint_seq ASC",
                (run_id,),
            )
            out = []
            for row in cur.fetchall():
                cp = self._row_to_checkpoint(row)
                self._fill_workflow(cp)
                self._verify_checksum(cp)
                out.append(cp)
            return out

    async def record_effect(self, record: EffectRecord) -> bool:
        return await self._run(lambda: self._record_effect(record))

    def _record_effect(self, record: EffectRecord) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO effects (execution_key, run_id, node_id, "
                "node_version, status, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.execution_key,
                    record.run_id,
                    record.node_id,
                    record.node_version,
                    record.status,
                    _dump(record.result_json),
                    record.created_at,
                ),
            )
            self._conn.commit()
            return cur.rowcount == 1

    async def get_effect(self, execution_key: str) -> EffectRecord | None:
        return await self._run(lambda: self._get_effect(execution_key))

    async def update_run_status(self, run_id: str, status: str) -> None:
        await self._run(lambda: self._update_run_status(run_id, status))

    def _update_run_status(self, run_id: str, status: str) -> None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, time.time(), run_id),
            )
            if cur.rowcount == 0:
                raise CheckpointError(
                    f"run {run_id!r} not found", field="run_id", actual=run_id
                )
            self._conn.commit()

    def _get_effect(self, execution_key: str) -> EffectRecord | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT execution_key, run_id, node_id, node_version, status, "
                "result_json, created_at FROM effects WHERE execution_key = ?",
                (execution_key,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return EffectRecord(
                execution_key=row[0],
                run_id=row[1],
                node_id=row[2],
                node_version=row[3],
                status=row[4],
                result_json=_load(row[5]),
                created_at=row[6],
            )

    async def close(self) -> None:
        await self._run(self._close)

    def _close(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.close()
        self._closed = True
