"""project_event_bus — in-process pub/sub for server → client push.

Tests the guarantees callers depend on:
  * publish never blocks producers, even when subscribers are slow
  * subscribers see events published after they subscribe
  * subscribers don't see events from other projects
  * cleanup is automatic when a subscription's context exits
  * subscriber_count reflects live subscriptions
"""
from __future__ import annotations

import asyncio

import pytest

from services.project_event_bus import (
    _QUEUE_MAX,
    _subscribers,
    publish,
    subscribe,
    subscriber_count,
)


@pytest.fixture(autouse=True)
def _clear_state():
    """Each test starts from a clean subscriber registry so ordering
    quirks between tests don't leak."""
    _subscribers.clear()
    yield
    _subscribers.clear()


@pytest.mark.asyncio
async def test_publish_to_no_subscribers_is_a_noop():
    """A producer that publishes before any subscriber has attached
    must not raise. Common at startup / for infrequent projects."""
    await publish("proj-a", {"type": "x"})   # no assertion; must not raise
    assert subscriber_count("proj-a") == 0


@pytest.mark.asyncio
async def test_subscriber_receives_published_event():
    async with subscribe("proj-a") as q:
        await publish("proj-a", {"type": "hello", "n": 1})
        got = await asyncio.wait_for(q.get(), timeout=1)
        assert got == {"type": "hello", "n": 1}


@pytest.mark.asyncio
async def test_events_do_not_leak_across_projects():
    """Publishing to project A never delivers to project B."""
    async with subscribe("proj-a") as qa, subscribe("proj-b") as qb:
        await publish("proj-a", {"type": "for-a"})
        await publish("proj-b", {"type": "for-b"})
        got_a = await asyncio.wait_for(qa.get(), timeout=1)
        got_b = await asyncio.wait_for(qb.get(), timeout=1)
        assert got_a == {"type": "for-a"}
        assert got_b == {"type": "for-b"}
        # Queues are empty — no cross-delivery.
        assert qa.empty() and qb.empty()


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive():
    """Two subscribers to the same project both see the same event."""
    async with subscribe("proj-a") as q1, subscribe("proj-a") as q2:
        await publish("proj-a", {"type": "broadcast"})
        got1 = await asyncio.wait_for(q1.get(), timeout=1)
        got2 = await asyncio.wait_for(q2.get(), timeout=1)
        assert got1 == got2 == {"type": "broadcast"}


@pytest.mark.asyncio
async def test_publish_never_blocks_when_subscriber_queue_is_full():
    """A slow subscriber that never drains its queue must not block
    the producer. Overflow drops the OLDEST event to keep newer ones."""
    async with subscribe("proj-a") as q:
        # Fill the queue past its max.
        for i in range(_QUEUE_MAX + 10):
            await publish("proj-a", {"type": "x", "i": i})
            # Never blocks — publish returns immediately.

        assert q.qsize() == _QUEUE_MAX
        # The FIRST event (i=0) was dropped in favor of newer ones.
        first = await q.get()
        assert first["i"] > 0


@pytest.mark.asyncio
async def test_subscription_cleaned_up_on_context_exit():
    """When a subscribe() context exits, the queue is removed from
    the registry — even if events were pending. Prevents leaks."""
    assert subscriber_count("proj-a") == 0
    async with subscribe("proj-a"):
        assert subscriber_count("proj-a") == 1
    assert subscriber_count("proj-a") == 0
    # Empty project entry pruned so idle projects don't linger.
    assert "proj-a" not in _subscribers


@pytest.mark.asyncio
async def test_events_published_before_subscribe_are_not_replayed():
    """The bus is real-time, not durable. Events fired with no
    subscribers are dropped; a later subscriber only sees what fires
    after it attaches. Callers needing history use the DB."""
    await publish("proj-a", {"type": "before"})
    async with subscribe("proj-a") as q:
        await publish("proj-a", {"type": "after"})
        got = await asyncio.wait_for(q.get(), timeout=1)
        assert got == {"type": "after"}
        assert q.empty()   # "before" was never queued for this subscriber
