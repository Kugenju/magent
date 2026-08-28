"""Read-only runtime context for a single agent invocation.

``Runtime`` is created by the executor for each agent call. It exposes the
``run_id``, the current agent name, a start timestamp and a logger. It is
deliberately minimal in phase 1: no retry policy, checkpoint store, tool
registry or LLM configuration lives here yet (those arrive in later
phases). Agents must not stash executor-internal mutable state on it.
"""

from __future__ import annotations

import logging
import time
import uuid


def new_run_id() -> str:
    """Generate a fresh run identifier."""
    return "run-" + uuid.uuid4().hex[:12]


class Runtime:
    """Immutable-ish context handed to an agent for one ``run`` call."""

    def __init__(
        self,
        run_id: str,
        agent_name: str,
        started_at: float,
        logger: logging.Logger,
    ) -> None:
        self.run_id = run_id
        self.agent_name = agent_name
        self.started_at = started_at
        self._logger = logger

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    def elapsed(self) -> float:
        """Seconds since this runtime was created."""
        return time.time() - self.started_at
