"""Reliability error types and retry classification (phase 4)."""

from __future__ import annotations

import asyncio

from magent.core.errors import (
    MagentError,
    StateMergeConflictError,
    StateUpdateError,
)
from magent.graph.errors import GraphValidationError


class RetryableError(MagentError):
    """Marker for an agent/business error that may be retried."""


class NonRetryableError(MagentError):
    """Marker for an error that must never be retried."""


class TemporaryError(RetryableError):
    """Example transient error (network blip, 429/5xx, lock timeout)."""


# Errors that must never be retried regardless of policy configuration.
DEFAULT_NON_RETRYABLE = (
    StateUpdateError,
    StateMergeConflictError,
    GraphValidationError,
    NonRetryableError,
)


def classify_exception(exc: BaseException, retryable_exceptions: tuple) -> bool:
    """Return True if ``exc`` should be retried under ``retryable_exceptions``."""
    if isinstance(exc, asyncio.CancelledError):
        return False
    if isinstance(exc, RetryableError):
        return True
    if isinstance(exc, retryable_exceptions):
        return True
    if isinstance(exc, DEFAULT_NON_RETRYABLE):
        return False
    return False


def classify_result(result) -> bool:
    """Return True if a returned ``FAILED`` AgentResult is explicitly retryable."""
    if result.error and result.error.get("retryable") is True:
        return True
    return False
