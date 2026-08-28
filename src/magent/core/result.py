"""Structured result returned by every agent.

An ``AgentResult`` is the only channel an agent uses to communicate back
to the executor. It never mutates the framework-held state object
directly; it only proposes partial ``updates`` that the executor merges.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ExecutionStatus(str, Enum):
    """Lifecycle status of an agent run or a step in an execution report."""

    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    # Used only in execution reports for agents that never started because
    # a previous agent failed under the fail-fast policy.
    NOT_EXECUTED = "not_executed"
    CANCELLED = "cancelled"


class AgentResult(BaseModel):
    """The structured outcome an agent returns from ``run``.

    Attributes:
        status: Whether the agent succeeded, was skipped, or failed.
        updates: A partial update to the shared state (field -> value).
            Unknown fields or type mismatches are rejected by the executor.
        message: Optional human-readable note.
        error: Optional structured error (type + reason), not a raw exception.
        metadata: Free-form execution metadata (timings, attempt counts...).
    """

    status: ExecutionStatus = ExecutionStatus.SUCCESS
    updates: dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = None
    error: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
