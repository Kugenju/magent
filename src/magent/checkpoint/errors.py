"""Checkpoint errors (phase 5)."""

from __future__ import annotations

from magent.core.errors import MagentError


class CheckpointError(MagentError):
    """Base class for checkpoint / recovery failures.

    Accepts optional ``field``/``expected``/``actual`` so the same constructor
    works for both plain checkpoint errors and compatibility conflicts.
    """

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        expected=None,
        actual=None,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.expected = expected
        self.actual = actual


class CheckpointCompatibilityError(CheckpointError):
    """A stored run cannot be resumed because of an incompatibility.

    Carries the offending ``field``, the ``expected`` value and the ``actual``
    value so callers can produce a precise diagnostic instead of guessing.
    """


class CheckpointConflictError(CheckpointError):
    """Same ``(run_id, checkpoint_seq)`` submitted with different content."""
