"""magent events package: an in-process EventBus for agent lifecycle events."""

from __future__ import annotations

from .bus import InMemoryEventBus, Subscription
from .errors import EventHandlerError
from .model import Event

# Public name used in the top-level API; the only in-process implementation
# shipped in phase 3 is the in-memory bus.
EventBus = InMemoryEventBus

__all__ = ["Event", "EventHandlerError", "InMemoryEventBus", "EventBus", "Subscription"]
