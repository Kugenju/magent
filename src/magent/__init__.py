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
    StateMergeConflictError,
    StateT,
    StateUpdateError,
    StepRecord,
    merge_updates,
    new_run_id,
)

from .graph import CompiledGraph, END, GraphBuilder, GraphExecutor, GraphValidationError
from .events import Event, EventBus, EventHandlerError
from .reliability import (
    NodeRunOutcome,
    ReliabilityPolicy,
    RetryableError,
    RetryPolicy,
    TemporaryError,
    TimeoutPolicy,
    run_node,
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
    "StateMergeConflictError",
    "GraphBuilder",
    "CompiledGraph",
    "END",
    "GraphValidationError",
    "GraphExecutor",
    "EventBus",
    "Event",
    "EventHandlerError",
    "ReliabilityPolicy",
    "RetryPolicy",
    "TimeoutPolicy",
    "RetryableError",
    "TemporaryError",
    "NodeRunOutcome",
    "run_node",
    "__version__",
]
