"""Phase-1 engineering closure tests (PHASE2 §3 entry conditions).

These pin down the closure items that the graph work depended on but were not
yet covered by an explicit regression test: collection fields use
``default_factory``, a conflicting update is rejected atomically (no partial
apply), and the core API imports no business / network / db / llm modules.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from magent import AgentResult, BaseAgent, ExecutionReport, SequentialExecutor


def test_agent_result_updates_default_factory():
    assert AgentResult().updates == {}


def test_agent_result_metadata_default_factory():
    assert AgentResult().metadata == {}


def test_execution_report_steps_default_factory():
    report = ExecutionReport(
        run_id="r", initial_state={}, final_state={},
        started_at=0.0, finished_at=0.0, duration_ms=0.0,
    )
    assert report.steps == []


class RichState(BaseModel):
    value: int = 0
    tag: str = ""
    messages: list[str] = Field(default_factory=list)


class Setter(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"value": 1, "messages": state.messages + ["x"]})


class Conflicting(BaseAgent):
    async def run(self, state, runtime):
        # value was already modified by Setter -> conflict under "reject";
        # tag is a brand new field. A correct atomic reject must drop BOTH.
        return AgentResult(updates={"value": 99, "tag": "boom"})


async def test_conflict_reject_is_atomic_no_partial_apply():
    executor = SequentialExecutor([Setter("a"), Conflicting("b")], conflict_strategy="reject")
    state, report = await executor.run(RichState())
    assert report.success is False
    assert state.value == 1  # only Setter's update applied
    assert state.tag == ""  # Conflicting's whole update rejected, not partially applied


def test_core_modules_have_no_forbidden_imports():
    core_dir = Path(__file__).resolve().parents[2] / "src" / "magent" / "core"
    forbidden = ("httpx", "sqlite3", "openai", "vulntell", "requests")
    for path in core_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in text, f"{path.name} imports forbidden '{name}'"
