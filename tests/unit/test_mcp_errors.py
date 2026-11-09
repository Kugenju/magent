"""Phase 10 — MCP error taxonomy, classification and reliability integration."""

from __future__ import annotations

from magent.core.errors import MagentError
from magent.mcp.errors import (
    KIND_ELICITATION_DENIED,
    KIND_FORBIDDEN,
    KIND_INVALID,
    KIND_PERMANENT,
    KIND_RATE_LIMITED,
    KIND_TIMEOUT,
    KIND_TRANSIENT,
    McpInvalidConfigError,
    McpPermanentError,
    McpRateLimitedError,
    McpTimeoutError,
    McpToolError,
    McpTransientError,
    build_tool_error,
    error_class_for_kind,
)
from magent.reliability.errors import RetryableError, classify_exception
from magent.tools.models import ToolError, ToolTimeoutError

_RETRYABLE_KINDS = (KIND_RATE_LIMITED, KIND_TIMEOUT, KIND_TRANSIENT)
_NON_RETRYABLE_KINDS = (KIND_FORBIDDEN, KIND_INVALID, KIND_PERMANENT, KIND_ELICITATION_DENIED)


def test_retryable_kinds_map_to_retryable_tool_errors():
    for kind in _RETRYABLE_KINDS:
        cls = error_class_for_kind(kind)
        assert issubclass(cls, ToolError)
        assert issubclass(cls, RetryableError)
        assert cls.retryable is True
        assert cls.kind == kind


def test_non_retryable_kinds_map_to_fail_fast_errors():
    for kind in _NON_RETRYABLE_KINDS:
        cls = error_class_for_kind(kind)
        assert issubclass(cls, ToolError)
        assert not issubclass(cls, RetryableError)
        assert cls.retryable is False
        assert cls.kind == kind


def test_timeout_error_is_also_a_tool_timeout():
    assert issubclass(McpTimeoutError, ToolTimeoutError)
    assert issubclass(McpTimeoutError, RetryableError)


def test_unknown_kind_is_conservative():
    cls = error_class_for_kind("totally_new_kind")
    assert cls is McpToolError
    assert cls.retryable is False


def test_build_tool_error_carries_context():
    err = build_tool_error(KIND_RATE_LIMITED, "mcp:srv__probe", "run-7", "slow down")
    assert isinstance(err, McpRateLimitedError)
    assert err.kind == KIND_RATE_LIMITED
    assert err.retryable is True
    assert err.component == "mcp:srv__probe"
    assert err.run_id == "run-7"
    assert "slow down" in str(err)


def test_build_tool_error_preserves_cause():
    cause = RuntimeError("boom")
    err = build_tool_error(KIND_TRANSIENT, "c", "r", "net hiccup", cause=cause)
    assert isinstance(err, McpTransientError)
    assert err.cause is cause


def test_classify_exception_sees_retryable_mcp_errors():
    assert classify_exception(McpRateLimitedError("c", "r", "x"), ()) is True
    assert classify_exception(McpTransientError("c", "r", "x"), ()) is True
    assert classify_exception(McpTimeoutError("c", "r", "x"), ()) is True


def test_classify_exception_never_retries_fail_fast_kinds():
    assert classify_exception(McpPermanentError("c", "r", "x"), ()) is False
    assert classify_exception(build_tool_error(KIND_FORBIDDEN, "c", "r", "x"), ()) is False


def test_mcp_invalid_config_is_framework_error():
    err = McpInvalidConfigError("bad config")
    assert isinstance(err, MagentError)
    assert not isinstance(err, ToolError)
    assert "bad config" in str(err)


def test_default_kind_token_on_base_class():
    err = McpToolError("c", "r", "unknown shape")
    assert err.kind == "mcp_error"
    assert err.retryable is False
    explicit = McpToolError("c", "r", "...", kind=KIND_PERMANENT)
    assert explicit.kind == KIND_PERMANENT
