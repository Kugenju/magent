"""Event model for the in-process EventBus.

An :class:`Event` is a structured, serializable record. Unlike a log string,
its ``payload`` is a typed mapping so subscribers can react to structured data
without parsing text.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


class Event(BaseModel):
    """A structured event delivered through an EventBus.

    Attributes:
        event_id: Unique id for this event (auto-generated).
        topic: Routing key, e.g. ``"agent.completed"``.
        run_id: The execution run this event belongs to.
        source: The node id or agent that produced the event.
        created_at: Monotonic-ish wall-clock timestamp (seconds).
        payload: Structured, schema-free extra data.
    """

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    topic: str
    run_id: Optional[str] = None
    source: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    payload: dict[str, Any] = Field(default_factory=dict)
