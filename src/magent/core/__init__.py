"""magent core: minimal multi-agent execution kernel (phase 1)."""

from __future__ import annotations

from .agent import BaseAgent
from .errors import (
    AgentError,
    DuplicateAgentNameError,
    MagentError,
    StateMergeConflictError,
    StateUpdateError,
)
from .executor import ExecutionReport, SequentialExecutor, StepRecord
from .result import AgentResult, ExecutionStatus
from .runtime import Runtime, new_run_id
from .state import StateT, merge_updates

__all__ = [
    "BaseAgent",
    "MagentError",
    "AgentError",
    "StateUpdateError",
    "StateMergeConflictError",
    "DuplicateAgentNameError",
    "AgentResult",
    "ExecutionStatus",
    "Runtime",
    "new_run_id",
    "merge_updates",
    "StateT",
    "SequentialExecutor",
    "ExecutionReport",
    "StepRecord",
]
