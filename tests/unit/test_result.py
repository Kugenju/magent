from __future__ import annotations

from magent import AgentResult, ExecutionStatus


def test_default_result_status_is_success():
    assert AgentResult().status == ExecutionStatus.SUCCESS


def test_status_enum_values():
    assert ExecutionStatus.SUCCESS.value == "success"
    assert ExecutionStatus.SKIPPED.value == "skipped"
    assert ExecutionStatus.FAILED.value == "failed"
    assert ExecutionStatus.NOT_EXECUTED.value == "not_executed"
