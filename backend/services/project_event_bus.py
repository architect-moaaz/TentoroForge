"""In-process per-project pub/sub for server → client push.

Motivation
----------
Self-heal runs as a background task, disconnected from the client's
request/response cycle. Without a push mechanism, the browser has to
poll ``/conversations`` to notice new messages, which is wasteful and
slow. Chat updates from a second tab have the same problem.

This module solves both with a small in-process event bus: any
producer can ``publish`` an event keyed by ``project_id``, and any
subscriber (typically an SSE handler) receives every event that
arrives for their project as long as their subscription is alive.

Scope
-----
Single-process only. If you ever run more than one uvicorn worker,
you'd need to swap this for Redis pub/sub or similar — the interface
here (``publish`` / ``subscribe``) is deliberately narrow so that
swap is a drop-in.

Contract
--------
* ``publish(project_id, event)`` — fires event to every current
  subscriber for that project. Non-blocking. Never raises.
* ``subscribe(project_id) -> AsyncIterator[dict]`` — yields events
  until the caller stops iterating. Cleans up its own queue on exit.

Events must be JSON-serializable. Callers should include a ``type``
field so subscribers can filter. Everything else is free-form.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

log = logging.getLogger(__name__)

# project_id (str) -> set of subscriber queues. WeakSet would be tidier
# but subscribers already clean up on their own via the async context
# manager below; plain set is simpler and equally correct.
_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

# Bound the per-subscriber queue so a slow client can't grow it
# unboundedly. Old events get dropped, newer ones are preferred.
_QUEUE_MAX = 256


async def publish(project_id: str, event: dict[str, Any]) -> None:
    """Fan an event out to every subscriber of ``project_id``.

    Never blocks a producer. Never raises — a slow subscriber whose
    queue is full has its oldest event dropped to make room. Callers
    that need delivery guarantees should use a durable channel; the
    bus is for real-time UX push, where losing a stale update is
    better than blocking the producer.
    """
    publish_nowait(project_id, event)


def publish_nowait(project_id: str, event: dict[str, Any]) -> None:
    """The same fan-out, callable from synchronous code.

    Nothing here ever awaits — every path is ``put_nowait`` — so the
    async ``publish`` above is this function with a coroutine wrapper
    for callers already in async context. Synchronous producers (the
    Blueprint DAG run, for one) call this one directly rather than
    having to find an event loop to schedule onto.
    """
    subs = _subscribers.get(project_id)
    if not subs:
        return
    # Copy so mutation during iteration is safe.
    for q in list(subs):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Drop the oldest to make room, then push. Never blocks.
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover — race, harmless
                pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover — race, harmless
                log.warning("project_event_bus: dropped event for %s", project_id)
        except Exception:  # noqa: BLE001
            log.exception("project_event_bus.publish failed for %s", project_id)


@asynccontextmanager
async def subscribe(project_id: str) -> AsyncIterator[asyncio.Queue]:
    """Register a subscriber and yield the queue events arrive on.

    Use as an async context manager so cleanup happens even if the
    caller aborts (e.g. the client disconnects the SSE stream). The
    yielded queue is a plain ``asyncio.Queue`` — the caller iterates
    it with ``await q.get()``.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers[project_id].add(q)
    try:
        yield q
    finally:
        _subscribers[project_id].discard(q)
        # Free the dict entry when the last subscriber leaves so idle
        # projects don't leak memory forever.
        if not _subscribers[project_id]:
            _subscribers.pop(project_id, None)


def subscriber_count(project_id: str) -> int:
    """How many active subscribers for a project. For tests + telemetry."""
    return len(_subscribers.get(project_id, ()))
