"""Checkpoint store contract and an in-memory implementation (phase 5)."""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from .errors import CheckpointConflictError, CheckpointError
from .models import CheckpointRecord, EffectRecord, RunRecord


@runtime_checkable
class CheckpointStore(Protocol):
    async def create_run(self, run: RunRecord) -> None: ...
    async def append(self, checkpoint: CheckpointRecord) -> None: ...
    async def latest(self, run_id: str) -> Optional[CheckpointRecord]: ...
    async def list_checkpoints(self, run_id: str) -> list[CheckpointRecord]: ...
    async def load_run(self, run_id: str) -> RunRecord: ...
    async def record_effect(self, record: EffectRecord) -> bool: ...
    async def get_effect(self, execution_key: str) -> Optional[EffectRecord]: ...
    async def update_run_status(self, run_id: str, status: str) -> None: ...
    async def close(self) -> None: ...


class InMemoryCheckpointStore:
    """Pure-Python store, useful for tests and processes without SQLite.

    Implements the same idempotency / conflict guarantees as the SQLite store:
    re-appending the same ``(run_id, checkpoint_seq)`` with identical content is
    a no-op, while different content raises :class:`CheckpointConflictError`.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._checkpoints: dict[str, list[CheckpointRecord]] = {}
        self._effects: dict[str, EffectRecord] = {}
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise CheckpointError("store is closed")

    async def create_run(self, run: RunRecord) -> None:
        self._check_open()
        if run.run_id in self._runs:
            raise CheckpointConflictError(
                f"run {run.run_id!r} already exists",
                field="run_id",
                expected="absent",
                actual=run.run_id,
            )
        self._runs[run.run_id] = run

    async def append(self, checkpoint: CheckpointRecord) -> None:
        self._check_open()
        seq = checkpoint.checkpoint_seq
        existing = next(
            (c for c in self._checkpoints.get(checkpoint.run_id, []) if c.checkpoint_seq == seq),
            None,
        )
        if existing is not None:
            if existing.checksum == checkpoint.checksum:
                return  # idempotent re-append
            raise CheckpointConflictError(
                f"checkpoint seq {seq} for run {checkpoint.run_id!r} already exists with different content",
                field="checkpoint_seq",
                expected=existing.checksum,
                actual=checkpoint.checksum,
            )
        self._checkpoints.setdefault(checkpoint.run_id, []).append(checkpoint)

    async def latest(self, run_id: str) -> Optional[CheckpointRecord]:
        self._check_open()
        cps = self._checkpoints.get(run_id)
        if not cps:
            return None
        return max(cps, key=lambda c: c.checkpoint_seq)

    async def load_run(self, run_id: str) -> RunRecord:
        self._check_open()
        run = self._runs.get(run_id)
        if run is None:
            raise CheckpointError(f"run {run_id!r} not found", field="run_id", actual=run_id)
        return run

    async def list_checkpoints(self, run_id: str) -> list[CheckpointRecord]:
        self._check_open()
        return sorted(
            self._checkpoints.get(run_id, []), key=lambda c: c.checkpoint_seq
        )

    async def record_effect(self, record: EffectRecord) -> bool:
        self._check_open()
        if record.execution_key in self._effects:
            return False  # already recorded → idempotent
        self._effects[record.execution_key] = record
        return True

    async def get_effect(self, execution_key: str) -> Optional[EffectRecord]:
        self._check_open()
        return self._effects.get(execution_key)

    async def update_run_status(self, run_id: str, status: str) -> None:
        self._check_open()
        run = self._runs.get(run_id)
        if run is None:
            raise CheckpointError(f"run {run_id!r} not found", field="run_id", actual=run_id)
        object.__setattr__(run, "status", status)

    async def close(self) -> None:
        self._closed = True
