"""Agent contract.

Every executable unit in magent implements ``BaseAgent``. It does not have
to use an LLM: rule-based, tool-based and LLM-based agents share the same
``run(state, runtime) -> AgentResult`` protocol. This uniformity is what
lets the executor schedule them interchangeably.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from .result import AgentResult
from .runtime import Runtime


class BaseAgent(ABC):
    """Abstract base class for all agents.

    Subclasses must set ``name`` (unique within one execution) and implement
    :meth:`run`. An agent reads the incoming ``state`` and returns an
    :class:`AgentResult` describing the partial state update it proposes; it
    must never mutate the framework-held state object directly.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    async def run(self, state: BaseModel, runtime: Runtime) -> AgentResult:
        """Execute the agent against ``state`` and return a result."""
        raise NotImplementedError
