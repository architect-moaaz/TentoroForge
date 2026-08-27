"""Persistent per-project SSE stream.

Motivation
----------
Self-heal, chat messages from other tabs, generation phase updates —
all of these are server → client push events. Without a persistent
stream, the frontend has to poll ``/conversations`` (wasteful, laggy)
or accept that some events are only visible after refresh (broken UX).

This endpoint subscribes the caller to the in-process event bus keyed
by ``project_id`` and streams every event that arrives, formatted as
SSE. The frontend opens ONE EventSource per project view and appends
events as they come in.

Design notes
------------
* One SSE connection per project view. Multiple tabs open the same
  project → multiple subscriptions on the bus, each gets its own copy.
* A ``ready`` event is sent on connect so the client can flip its
  connection state without waiting for the first real event.
* A ``ping`` is sent every 25s to keep proxies from cutting idle
  connections (nginx default is 60s; 25s stays well under any common
  ceiling).
* Client disconnect triggers ``asyncio.CancelledError`` in the loop,
  which unwinds the ``subscribe`` context and cleans up the queue.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from services.project_event_bus import subscribe

log = logging.getLogger(__name__)
router = APIRouter()

# How long we wait for a new event before emitting a keepalive ping.
# 25s stays under nginx / cloudflare / most proxy idle-cut ceilings.
_PING_INTERVAL_SECONDS = 25


@router.get("/api/projects/{project_id}/events")
async def project_events(project_id: uuid.UUID) -> EventSourceResponse:
    """Persistent SSE stream for real-time project events.

    Emitted event types (grow over time; frontend filters by name):
      * ``ready``           — sent once on connect. no data.
      * ``ping``            — sent every ~25s to keep the connection alive.
      * ``self_heal_message`` — Smith authored a chat message after
        healing a runtime exception. Payload: {conversation_id, role,
        content, metadata, created_at}.
      * ``chat_message``    — a new assistant/user message landed
        (e.g. from another tab or a Smith turn). Same payload shape.
    """
    pid_str = str(project_id)

    async def _stream() -> AsyncIterator[dict[str, Any]]:
        async with subscribe(pid_str) as q:
            # Tell the client we're live so it can flip its "connected"
            # state without waiting for something else to happen.
            yield {"event": "ready", "data": json.dumps({"project_id": pid_str})}
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=_PING_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    # Idle — send a ping so the proxy doesn't cut us.
                    yield {"event": "ping", "data": "{}"}
                    continue
                except asyncio.CancelledError:
                    # Client disconnected — subscribe() context cleans
                    # up the queue registration on the way out.
                    raise
                # Every published event MUST include ``type``. That's
                # the SSE event name the frontend filters on.
                name = event.get("type") or "message"
                payload = {k: v for k, v in event.items() if k != "type"}
                yield {"event": name, "data": json.dumps(payload, default=str)}

    return EventSourceResponse(_stream())
