"""Checkpoint, recovery and idempotency (phase 5).

Public surface:
- ``CheckpointStore`` (protocol) and ``InMemoryCheckpointStore`` / ``SqliteCheckpointStore``.
- Records: ``RunRecord``, ``CheckpointRecord``, ``EffectRecord``, ``CheckpointPhase``.
- Errors: ``CheckpointError``, ``CheckpointCompatibilityError``, ``CheckpointConflictError``.
- Idempotency: ``execution_key``, ``SideEffectSink``.
"""

from __future__ import annotations

from .errors import (
    CheckpointCompatibilityError,
    CheckpointConflictError,
    CheckpointError,
)
from .idempotency import SideEffectSink, execution_key
from .models import (
    SCHEMA_VERSION,
    CheckpointPhase,
    CheckpointRecord,
    EffectRecord,
    RunRecord,
    canonical_json,
    checksum_of,
    state_schema_hash,
    state_type_name,
)
from .sqlite import SqliteCheckpointStore
from .store import CheckpointStore, InMemoryCheckpointStore

__all__ = [
    "CheckpointStore",
    "InMemoryCheckpointStore",
    "SqliteCheckpointStore",
    "RunRecord",
    "CheckpointRecord",
    "EffectRecord",
    "CheckpointPhase",
    "CheckpointError",
    "CheckpointCompatibilityError",
    "CheckpointConflictError",
    "SideEffectSink",
    "execution_key",
    "SCHEMA_VERSION",
    "canonical_json",
    "checksum_of",
    "state_schema_hash",
    "state_type_name",
]
