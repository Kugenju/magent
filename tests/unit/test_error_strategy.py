import asyncio
import logging

import pytest
from pydantic import BaseModel

from magent import (
    AgentResult,
    BaseAgent,
    ExecutionStatus,
    ReliabilityPolicy,
    RetryableError,
    RetryPolicy,
    SequentialExecutor,
)
from magent.core.errors import StateUpdateError
from magent.core.runtime import Runtime, new_run_id
from magent.reliability.errors import NonRetryableError
from magent.reliability.runner import run_node


class S(BaseModel):
    value: int = 0


def noop_sleeper(_=0):
    return asyncio.sleep(0)


def rt(name="a"):
    return Runtime(
        run_id=new_run_id(),
        agent_name=name,
        started_at=0.0,
        logger=logging.getLogger("test"),
    )


class RetryThenOk(BaseAgent):
    def __init__(self, name, fail_times):
        super().__init__(name)
        self.calls = 0
        self.fail_times = fail_times

    async def run(self, state, runtime):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RetryableError("transient")
        return AgentResult(updates={"value": state.value + 1})


class AlwaysRetryableFail(BaseAgent):
    def __init__(self, name):
        super().__init__(name)
        self.calls = 0

    async def run(self, state, runtime):
        self.calls += 1
        raise RetryableError("always")


class NonRetryableFail(BaseAgent):
    def __init__(self, name):
        super().__init__(name)
        self.calls = 0

    async def run(self, state, runtime):
        self.calls += 1
        raise NonRetryableError("fatal")


class BadField(BaseAgent):
    def __init__(self, name="a"):
        super().__init__(name)
        self.calls = 0

    async def run(self, state, runtime):
        self.calls += 1
        raise StateUpdateError("bad field")


async def test_retryable_error_is_retried_until_success():
    agent = RetryThenOk("a", fail_times=2)
    policy = ReliabilityPolicy(retry=RetryPolicy(max_attempts=3, backoff_base=0.0))
    outcome = await run_node(
        agent, S(), rt(), policy=policy, sleeper=noop_sleeper, rng=lambda: 0.0
    )
    assert outcome.status == ExecutionStatus.SUCCESS
    assert agent.calls == 3
    assert len(outcome.attempts) == 3


async def test_retryable_error_exhausts_attempts():
    agent = AlwaysRetryableFail("a")
    policy = ReliabilityPolicy(retry=RetryPolicy(max_attempts=3, backoff_base=0.0))
    outcome = await run_node(
        agent, S(), rt(), policy=policy, sleeper=noop_sleeper, rng=lambda: 0.0
    )
    assert outcome.status == ExecutionStatus.FAILED
    assert agent.calls == 3
    assert outcome.terminal_reason == "failed"


async def test_non_retryable_error_not_retried():
    agent = NonRetryableFail("a")
    policy = ReliabilityPolicy(retry=RetryPolicy(max_attempts=5, backoff_base=0.0))
    outcome = await run_node(
        agent, S(), rt(), policy=policy, sleeper=noop_sleeper, rng=lambda: 0.0
    )
    assert outcome.status == ExecutionStatus.FAILED
    assert agent.calls == 1
    assert len(outcome.attempts) == 1


async def test_state_update_error_not_retried():
    agent = BadField("a")
    policy = ReliabilityPolicy(retry=RetryPolicy(max_attempts=5, backoff_base=0.0))
    outcome = await run_node(
        agent, S(), rt(), policy=policy, sleeper=noop_sleeper, rng=lambda: 0.0
    )
    assert outcome.status == ExecutionStatus.FAILED
    assert agent.calls == 1


async def test_custom_retryable_exception():
    class MyTransient(Exception):
        pass

    class CustomRetry(BaseAgent):
        def __init__(self, name):
            super().__init__(name)
            self.calls = 0

        async def run(self, state, runtime):
            self.calls += 1
            if self.calls <= 1:
                raise MyTransient()
            return AgentResult(updates={"value": state.value + 1})

    agent = CustomRetry("a")
    policy = ReliabilityPolicy(
        retry=RetryPolicy(
            max_attempts=3, backoff_base=0.0, retryable_exceptions=(MyTransient,)
        )
    )
    outcome = await run_node(
        agent, S(), rt(), policy=policy, sleeper=noop_sleeper, rng=lambda: 0.0
    )
    assert outcome.status == ExecutionStatus.SUCCESS
    assert agent.calls == 2


async def test_result_error_retryable_flag():
    class RetryViaResult(BaseAgent):
        def __init__(self, name):
            super().__init__(name)
            self.calls = 0

        async def run(self, state, runtime):
            self.calls += 1
            if self.calls <= 1:
                return AgentResult(
                    status=ExecutionStatus.FAILED,
                    error={"retryable": True, "reason": "transient"},
                )
            return AgentResult(updates={"value": state.value + 1})

    agent = RetryViaResult("a")
    policy = ReliabilityPolicy(retry=RetryPolicy(max_attempts=3, backoff_base=0.0))
    outcome = await run_node(
        agent, S(), rt(), policy=policy, sleeper=noop_sleeper, rng=lambda: 0.0
    )
    assert outcome.status == ExecutionStatus.SUCCESS
    assert agent.calls == 2


async def test_sequential_report_retry_count():
    agent = RetryThenOk("a", fail_times=2)
    state, report = await SequentialExecutor(
        [agent],
        reliability=ReliabilityPolicy(retry=RetryPolicy(max_attempts=3, backoff_base=0.0)),
        sleeper=noop_sleeper,
        rng=lambda: 0.0,
    ).run(S())
    assert report.success is True
    assert report.retry_count == 2
