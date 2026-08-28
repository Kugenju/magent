from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from magent import (
    AgentResult,
    BaseAgent,
    DuplicateAgentNameError,
    ExecutionStatus,
    SequentialExecutor,
)


class DemoState(BaseModel):
    value: int = 0
    messages: list[str] = Field(default_factory=list)


class Producer(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(
            updates={"value": state.value + 1, "messages": state.messages + ["p"]},
            message="produced",
        )


class Consumer(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(
            updates={"messages": state.messages + [f"c:{state.value}"]},
            message="consumed",
        )


async def test_sequential_execution_propagates_updates():
    executor = SequentialExecutor([Producer("p"), Consumer("c")])
    state, report = await executor.run(DemoState())
    assert state.value == 1
    assert state.messages == ["p", "c:1"]
    assert report.success
    assert [s.status for s in report.steps] == [
        ExecutionStatus.SUCCESS,
        ExecutionStatus.SUCCESS,
    ]


async def test_duplicate_agent_name_rejected_before_run():
    with pytest.raises(DuplicateAgentNameError):
        SequentialExecutor([Producer("same"), Consumer("same")])


async def test_empty_agent_list_returns_success_report():
    executor = SequentialExecutor([])
    state, report = await executor.run(DemoState())
    assert report.steps == []
    assert report.success
    assert state.value == 0


class Boomer(BaseAgent):
    async def run(self, state, runtime):
        raise RuntimeError("boom")


class AfterBoom(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"value": 99})


async def test_agent_exception_fails_fast_and_skips_rest():
    executor = SequentialExecutor([Boomer("boom"), AfterBoom("after")])
    state, report = await executor.run(DemoState())
    assert report.success is False
    assert report.failed_agent == "boom"
    statuses = {s.agent_name: s.status for s in report.steps}
    assert statuses["boom"] == ExecutionStatus.FAILED
    assert statuses["after"] == ExecutionStatus.NOT_EXECUTED
    assert state.value == 0


async def test_agent_exception_records_unified_agent_error():
    executor = SequentialExecutor([Boomer("boom")])
    state, report = await executor.run(DemoState())
    step = report.steps[0]
    assert step.status == ExecutionStatus.FAILED
    assert step.error is not None
    assert step.error["type"] == "AgentError"
    assert step.error["agent_name"] == "boom"
    assert step.error["cause"] == "RuntimeError"
    assert state.value == 0


class Failer(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(
            status=ExecutionStatus.FAILED,
            error={"type": "BizError", "reason": "bad input"},
        )


async def test_explicit_failed_result_stops_pipeline():
    executor = SequentialExecutor([Failer("f"), AfterBoom("a")])
    state, report = await executor.run(DemoState())
    assert report.success is False
    assert report.failed_agent == "f"


class BadUpdater(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"unknown_field": 1})


async def test_unknown_field_update_fails_agent():
    executor = SequentialExecutor([BadUpdater("bad")])
    state, report = await executor.run(DemoState())
    assert report.success is False
    assert report.steps[0].status == ExecutionStatus.FAILED


class SetterA(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"value": 1})


class SetterB(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={"value": 2})


async def test_conflict_reject_strategy_fails_second_writer():
    executor = SequentialExecutor(
        [SetterA("a"), SetterB("b")], conflict_strategy="reject"
    )
    state, report = await executor.run(DemoState())
    assert report.success is False
    assert report.steps[1].status == ExecutionStatus.FAILED


async def test_fixed_run_id_and_non_negative_duration():
    executor = SequentialExecutor([Producer("p")], run_id="fixed-1")
    state, report = await executor.run(DemoState())
    assert report.run_id == "fixed-1"
    assert report.duration_ms >= 0
    assert state.value == 1


class Skipper(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(status=ExecutionStatus.SKIPPED, message="skip")


async def test_skipped_agent_does_not_update_and_continues():
    executor = SequentialExecutor([Skipper("s"), Producer("p")])
    state, report = await executor.run(DemoState())
    assert report.success
    assert ExecutionStatus.SKIPPED in [s.status for s in report.steps]
    assert state.value == 1  # producer still ran after the skip
