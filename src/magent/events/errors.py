"""Event handler exceptions for the in-process EventBus.

Handler failures are distinct from agent failures: the EventBus is a
best-effort side channel and must never corrupt the core execution state.
"""

from __future__ import annotations

from magent.core.errors import MagentError


class EventHandlerError(MagentError):
    """Raised when an event handler fails and the bus is configured to propagate.

    By default :class:`InMemoryEventBus` logs handler failures and continues;
    only when ``fail_on_handler_error=True`` is it raised.
    """

    def __init__(self, topic: str, reason: str, *, handler=None, cause=None) -> None:
        self.topic = topic
        self.reason = reason
        self.handler = handler
        self.cause = cause
        super().__init__(f"event handler failed on topic {topic!r}: {reason}")
