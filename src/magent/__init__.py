"""magent: a minimal, reusable, recoverable multi-agent execution framework.

This top-level package re-exports the stable phase-1 public API: the agent
contract, typed state merging, structured results, the runtime context and
the deterministic sequential executor. Later phases add Graph, concurrency,
EventBus, checkpointing and observability on top of these primitives.
"""

from __future__ import annotations

from .core import (
    AgentError,
    AgentResult,
    BaseAgent,
    DuplicateAgentNameError,
    ExecutionReport,
    ExecutionStatus,
    MagentError,
    Runtime,
    SequentialExecutor,
    StateT,
    StateUpdateError,
    StepRecord,
    merge_updates,
    new_run_id,
)

__version__ = "0.1.0"

__all__ = [
    "BaseAgent",
    "MagentError",
    "AgentError",
    "StateUpdateError",
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
    "__version__",
]
