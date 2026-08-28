"""Framework exceptions for magent.

Errors are split into two families:

- Agent business failures (``AgentError``): an agent ran but could not
  complete its work, or it explicitly returned a ``FAILED`` result.
- Framework execution failures (``StateUpdateError``,
  ``DuplicateAgentNameError``): the contract between agent and executor
  was violated.
"""

from __future__ import annotations


class MagentError(Exception):
    """Base class for every error raised by the magent framework."""


class AgentError(MagentError):
    """Raised when an agent fails during execution.

    Carries enough context to attribute the failure to a specific agent
    and run without leaking the raw cause into unrelated surfaces.
    """

    def __init__(
        self,
        agent_name: str,
        run_id: str,
        message: str,
        *,
        cause: BaseException | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.run_id = run_id
        self.cause = cause
        super().__init__(f"agent '{agent_name}' failed (run={run_id}): {message}")


class StateUpdateError(MagentError):
    """Raised when an agent returns an invalid state update.

    Invalid means: an unknown field, a type mismatch, or a conflicting
    update under the ``reject`` conflict strategy.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"invalid state update: {reason}")


class DuplicateAgentNameError(MagentError):
    """Raised when two agents in one execution share the same name."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"duplicate agent name: '{name}'")
