"""State contract and partial-update merging.

The framework does not prescribe a single state class. Instead it accepts
any user-defined Pydantic model and requires agents to return *partial*
updates. Merging is shallow at the field level: a provided field replaces
the previous value. Unknown fields and type mismatches are rejected so
that state corruption fails loudly rather than silently.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .errors import StateUpdateError

StateT = TypeVar("StateT", bound=BaseModel)


def merge_updates(state: StateT, updates: dict[str, Any]) -> StateT:
    """Return a new state with ``updates`` applied, validating the result.

    Args:
        state: The current state instance.
        updates: Partial field updates proposed by an agent.

    Returns:
        A new ``StateT`` instance with the updates merged in.

    Raises:
        StateUpdateError: If ``updates`` is not a mapping, contains a field
            not declared on the state model, or fails type validation.
    """
    if not isinstance(updates, dict):
        raise StateUpdateError(f"updates must be a mapping, got {type(updates).__name__}")

    unknown = [key for key in updates if key not in type(state).model_fields]
    if unknown:
        raise StateUpdateError(f"unknown fields: {sorted(unknown)}")

    try:
        merged = type(state).model_validate({**state.model_dump(), **updates})
    except ValidationError as exc:
        raise StateUpdateError(str(exc)) from exc
    return merged
