"""Immutable reliability policy objects (phase 4, §4)."""

from __future__ import annotations

from typing import Optional, Tuple


class _Immutable:
    """Mixin enforcing immutability after construction."""

    _frozen = False

    def __setattr__(self, name, value):
        if self._frozen:
            raise AttributeError(
                f"cannot mutate immutable {type(self).__name__} instance"
            )
        object.__setattr__(self, name, value)


class RetryPolicy(_Immutable):
    """Bounded exponential-backoff retry configuration.

    ``max_attempts`` is the total number of executions (initial call + retries).
    A default policy is ``max_attempts=1`` (no retries), preserving the old
    fail-fast behaviour.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 1,
        backoff_base: float = 0.5,
        backoff_max: float = 30.0,
        jitter: float = 0.1,
        retryable_exceptions: Tuple[type, ...] = (),
    ) -> None:
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {max_attempts!r}")
        if backoff_base < 0:
            raise ValueError(f"backoff_base must be >= 0, got {backoff_base!r}")
        if backoff_max < backoff_base:
            raise ValueError(
                f"backoff_max ({backoff_max}) must be >= backoff_base ({backoff_base})"
            )
        if jitter < 0 or jitter > 1:
            raise ValueError(f"jitter must be in [0, 1], got {jitter!r}")
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.jitter = jitter
        self.retryable_exceptions = tuple(retryable_exceptions)
        object.__setattr__(self, "_frozen", True)

    def should_retry(self, attempt: int) -> bool:
        """Whether another attempt is allowed after ``attempt`` (1-based)."""
        return attempt < self.max_attempts

    def backoff_delay(self, attempt: int, rng) -> float:
        """Compute the delay before the next attempt.

        ``delay = min(backoff_max, backoff_base * 2**(attempt-1)) + jitter*rng()``.
        ``rng`` returns a float in ``[0, 1)``.
        """
        exponential = self.backoff_base * (2 ** (attempt - 1))
        capped = min(self.backoff_max, exponential)
        return capped + self.jitter * rng()


class TimeoutPolicy(_Immutable):
    """Node-level timeout configuration (phase 4, §6)."""

    def __init__(self, *, node_timeout: Optional[float] = None) -> None:
        if node_timeout is not None and node_timeout < 0:
            raise ValueError(f"node_timeout must be >= 0, got {node_timeout!r}")
        self.node_timeout = node_timeout
        object.__setattr__(self, "_frozen", True)


class ReliabilityPolicy(_Immutable):
    """Combined reliability policy for an executor run.

    Args:
        retry: ``RetryPolicy`` (defaults to no retries).
        timeout: ``TimeoutPolicy`` (defaults to no timeout).
        on_failure: Failure strategy. Only ``"fail_fast"`` is enabled in phase 4.
    """

    def __init__(
        self,
        *,
        retry: Optional[RetryPolicy] = None,
        timeout: Optional[TimeoutPolicy] = None,
        on_failure: str = "fail_fast",
    ) -> None:
        self.retry = retry or RetryPolicy()
        self.timeout = timeout or TimeoutPolicy()
        if on_failure != "fail_fast":
            raise ValueError(
                f"unknown on_failure strategy: {on_failure!r} "
                "(phase 4 only supports 'fail_fast')"
            )
        self.on_failure = on_failure
        object.__setattr__(self, "_frozen", True)
