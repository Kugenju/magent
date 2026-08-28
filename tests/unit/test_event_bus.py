"""Tests for the in-process EventBus (phase 3, §7 / §10)."""

from __future__ import annotations

import pytest

from magent import Event, EventBus, EventHandlerError


async def test_multiple_subscribers_receive_event():
    bus = EventBus()
    seen_a, seen_b = [], []
    await bus.subscribe("t", lambda e: seen_a.append(e))
    await bus.subscribe("t", lambda e: seen_b.append(e))
    await bus.publish(Event(topic="t", payload={"x": 1}))
    assert len(seen_a) == 1 and len(seen_b) == 1
    assert seen_a[0].payload["x"] == 1


async def test_delivery_order_within_topic_is_preserved():
    bus = EventBus()
    order = []
    await bus.subscribe("t", lambda e: order.append(e.payload["i"]))
    for i in range(5):
        await bus.publish(Event(topic="t", payload={"i": i}))
    assert order == [0, 1, 2, 3, 4]


async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    seen = []
    sub = await bus.subscribe("t", lambda e: seen.append(e))
    await bus.publish(Event(topic="t"))
    sub.unsubscribe()
    await bus.publish(Event(topic="t"))
    assert len(seen) == 1


async def test_handler_exception_does_not_stop_others():
    bus = EventBus()
    good, bad = [], []

    def boom(e):
        bad.append(e)
        raise RuntimeError("nope")

    await bus.subscribe("t", boom)
    await bus.subscribe("t", lambda e: good.append(e))
    await bus.publish(Event(topic="t"))
    assert len(good) == 1
    assert len(bad) == 1
    assert bus.stats()["handler_errors"] == 1


async def test_fail_on_handler_error_raises():
    bus = EventBus(fail_on_handler_error=True)
    await bus.subscribe("t", lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(EventHandlerError):
        await bus.publish(Event(topic="t"))


async def test_closed_bus_rejects_publish_and_subscribe():
    bus = EventBus()
    await bus.close()
    with pytest.raises(EventHandlerError):
        await bus.publish(Event(topic="t"))
    with pytest.raises(EventHandlerError):
        await bus.subscribe("t", lambda e: None)


async def test_bus_does_not_mutate_event_payload():
    bus = EventBus()
    captured = {}

    def handler(e: Event):
        captured["e"] = e

    await bus.subscribe("t", handler)
    payload = {"k": [1, 2, 3]}
    await bus.publish(Event(topic="t", payload=payload))
    # The bus must not alter the payload it was given.
    assert captured["e"].payload == {"k": [1, 2, 3]}


async def test_stats_track_published_and_by_topic():
    bus = EventBus()
    await bus.subscribe("a", lambda e: None)
    await bus.publish(Event(topic="a"))
    await bus.publish(Event(topic="a"))
    await bus.publish(Event(topic="b"))
    stats = bus.stats()
    assert stats["published"] == 3
    assert stats["by_topic"] == {"a": 2, "b": 1}
