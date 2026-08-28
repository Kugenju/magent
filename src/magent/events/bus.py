"""In-process, at-most-once EventBus.

The bus is a side channel: it never participates in state merging or control
flow. Agents publish lifecycle events; subscribers observe them. Handler
failures are isolated so one bad subscriber cannot break the others.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Union

from .errors import EventHandlerError
from .model import Event

Handler = Callable[[Event], Union[None, Awaitable[None]]]

_log = logging.getLogger("magent.events")


class Subscription:
    """A handle returned by :meth:`InMemoryEventBus.subscribe`."""

    __slots__ = ("_bus", "_topic", "_handler")

    def __init__(self, bus: "InMemoryEventBus", topic: str, handler: Handler) -> None:
        self._bus = bus
        self._topic = topic
        self._handler = handler

    def unsubscribe(self) -> None:
        self._bus.unsubscribe(self._topic, self._handler)


class InMemoryEventBus:
    """Memory-only publish/subscribe bus with ordered per-topic delivery.

    Args:
        fail_on_handler_error: When ``False`` (default) a handler exception is
            logged and the bus continues notifying other subscribers. When
            ``True`` the offending error is wrapped in
            :class:`EventHandlerError` and raised from ``publish``.
    """

    def __init__(self, *, fail_on_handler_error: bool = False) -> None:
        self._fail_on_handler_error = fail_on_handler_error
        self._topics: dict[str, list[Handler]] = {}
        self._closed = False
        self._published = 0
        self._by_topic: dict[str, int] = {}
        self._handler_errors = 0

    async def subscribe(self, topic: str, handler: Handler) -> Subscription:
        if self._closed:
            raise EventHandlerError(topic, "cannot subscribe on a closed bus")
        if not callable(handler):
            raise EventHandlerError(topic, "handler must be callable")
        self._topics.setdefault(topic, []).append(handler)
        return Subscription(self, topic, handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        subscribers = self._topics.get(topic)
        if subscribers and handler in subscribers:
            subscribers.remove(handler)

    async def publish(self, event: Event) -> None:
        if self._closed:
            raise EventHandlerError(event.topic, "cannot publish on a closed bus")
        self._published += 1
        self._by_topic[event.topic] = self._by_topic.get(event.topic, 0) + 1
        for handler in list(self._topics.get(event.topic, [])):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - isolate handler failures
                self._handler_errors += 1
                if self._fail_on_handler_error:
                    raise EventHandlerError(
                        event.topic, str(exc), handler=handler, cause=exc
                    ) from exc
                _log.warning("event handler failed on topic %r: %s", event.topic, exc)

    async def close(self) -> None:
        self._closed = True

    def stats(self) -> dict:
        """Return a snapshot of delivery statistics for reports/tests."""
        return {
            "published": self._published,
            "by_topic": dict(self._by_topic),
            "handler_errors": self._handler_errors,
            "closed": self._closed,
        }
