"""Checkpoint domain models and serialization (phase 5, §4).

A checkpoint is a complete, independently verifiable record — never a log
cache. Every record carries a checksum over its canonical JSON so a corrupted
or partially written snapshot is rejected on read, not trusted by modification
time.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


SCHEMA_VERSION = 1


class CheckpointPhase(str, Enum):
    RUN_STARTED = "run_started"
    NODE_STARTED = "node_started"
    NODE_COMMITTED = "node_committed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


def _canonical_default(o):
    if isinstance(o, BaseModel):
        return o.model_dump()
    if isinstance(o, Enum):
        return o.value
    raise TypeError(f"cannot serialize {type(o).__name__} to canonical JSON")


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no whitespace, aware of pydantic/enum."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_canonical_default,
    )


def checksum_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def state_type_name(state_cls) -> str:
    return getattr(state_cls, "__name__", str(state_cls))


def state_schema_hash(state_cls) -> str:
    """Stable hash of a pydantic model's JSON schema."""
    schema = state_cls.model_json_schema()
    return checksum_of(canonical_json(schema))[:16]


class RunRecord(BaseModel):
    run_id: str
    workflow_id: str
    workflow_version: str
    state_type: str
    state_schema_hash: str
    initial_state: dict[str, Any]
    status: str
    created_at: float
    updated_at: float


class CheckpointRecord(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    workflow_id: str
    workflow_version: str
    node_id: Optional[str] = None
    node_version: Optional[str] = None
    checkpoint_seq: int
    phase: CheckpointPhase
    attempt: Optional[int] = None
    state_type: str
    state_schema_hash: str
    input_state: Optional[dict[str, Any]] = None
    output_state: Optional[dict[str, Any]] = None
    updates: Optional[dict[str, Any]] = None
    route: Optional[dict[str, Any]] = None
    activated_nodes: Optional[list[str]] = None
    frontier: Optional[dict[str, Any]] = None
    attempts: list[dict[str, Any]] = []
    created_at: float
    checksum: str = ""

    def model_post_init(self, __context) -> None:
        if not self.checksum:
            object.__setattr__(self, "checksum", self.compute_checksum())

    def canonical(self) -> str:
        return canonical_json(self.model_dump())

    def compute_checksum(self) -> str:
        payload = self.model_dump(exclude={"checksum"})
        return checksum_of(canonical_json(payload))


class EffectRecord(BaseModel):
    execution_key: str
    run_id: str
    node_id: str
    node_version: str
    status: str
    result_json: dict[str, Any]
    created_at: float
