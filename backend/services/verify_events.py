"""JV-21 — In-memory pubsub for in-flight verify events.

The verify pass runs on a background asyncio task with no HTTP request
attached; its SSE-shaped events (journey_result, journey_gate, log,
office) are consumed internally by ``_collect_journey_events``. This
module lets a *later* HTTP subscriber (a browser opening
``/api/projects/{id}/verify/events``) receive the same events live.

Design:
  - One asyncio.Queue per (project_id, subscriber). ``subscribe()`` mints
    a queue and registers it; ``unsubscribe()`` removes and drains it.
  - ``publish(project_id, event)`` fan-outs to every currently-registered
    subscriber for that project. Backpressure = drop (bounded queue,
    ``put_nowait`` with exception swallowed) — a slow consumer never
    stalls the verify pass.
  - Single-process only. If we ever run multiple uvicorn workers or
    horizontal scale, this becomes Redis pubsub.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# project_id → list of live subscriber queues
_SUBS: dict[str, list[asyncio.Queue]] = defaultdict(list)

_MAX_BUFFERED = 256  # per-subscriber ceiling; older events drop on overflow


def _key(project_id: uuid.UUID | str) -> str:
    return str(project_id)


def subscribe(project_id: uuid.UUID | str) -> asyncio.Queue:
    """Register a new subscriber. Returns its queue.

    Call ``unsubscribe(project_id, q)`` in a finally block to clean up.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_BUFFERED)
    _SUBS[_key(project_id)].append(q)
    return q


def unsubscribe(project_id: uuid.UUID | str, q: asyncio.Queue) -> None:
    subs = _SUBS.get(_key(project_id))
    if not subs:
        return
    try:
        subs.remove(q)
    except ValueError:
        pass
    if not subs:
        _SUBS.pop(_key(project_id), None)


def publish(project_id: uuid.UUID | str, event: dict[str, Any]) -> None:
    """Fan-out one event to every current subscriber for the project.

    ``event`` should be the shape ``{"event": "<name>", "data": "<json-str>"}``
    matching the SSE wire format used elsewhere. This mirrors
    ``services.journey_gate._sse``.

    Non-blocking. If a subscriber's queue is full, the event is dropped
    for that subscriber only (the pubsub never stalls the producer).
    """
    subs = _SUBS.get(_key(project_id))
    if not subs:
        return
    for q in subs:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Slow consumer — drop the event for them. Warn once per
            # occurrence so drops don't stay silent forever.
            logger.warning(
                "verify_events: dropping event for %s (queue full, kind=%s)",
                _key(project_id), event.get("event"),
            )


def publish_lifecycle(project_id: uuid.UUID | str, kind: str, **fields: Any) -> None:
    """Convenience for lifecycle markers (verify_start, verify_end).

    These aren't emitted by journey_gate — the pubsub owns them so a
    late subscriber can still tell whether a run is in flight.
    """
    import json as _json
    publish(project_id, {"event": kind, "data": _json.dumps(fields)})


def has_subscribers(project_id: uuid.UUID | str) -> bool:
    return bool(_SUBS.get(_key(project_id)))
