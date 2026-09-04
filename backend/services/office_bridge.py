"""Wire a Blueprint DAG run to the virtual office on screen.

Every run writes an account of itself to a ledger
(``services.blueprint.run_ledger``), and a ledger hands each line to its
observer as it is written. The office is one such observer — a second
reader of the run's own record rather than a second record. This module
is the adapter, and it is deliberately the only place that knows both
ends: the orchestrator never imports the event bus, and the office never
imports the DAG.

    from services.office_bridge import office_sink

    run(svc, executor, plan=plan, observer=office_sink(project_id))

Events land on the per-project SSE stream (``/api/projects/{id}/events``)
under the event name ``office``, with the office event itself under the
``office`` key. The frontend forwards that payload straight into the
office store, which is the same shape the legacy relay's
``sse_event("office", ...)`` frames carry.

Threading
---------
A DAG run is synchronous and blocking, so a request handler runs it in a
worker thread — but the bus hands events to ``asyncio.Queue``s owned by
the event loop, and ``put_nowait`` from another thread is not safe. So a
sink created while a loop is running captures it and marshals every
publish back with ``call_soon_threadsafe``. A sink created without a loop
(the CLI) publishes inline, because there is no loop to be wrong about.
"""

from __future__ import annotations

import asyncio
import logging

from services.office_events import OfficeNarrator
from services.project_event_bus import publish_nowait

log = logging.getLogger(__name__)


def office_sink(
    project_id: str | None,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> OfficeNarrator | None:
    """A run-ledger observer that drives the office for one project.

    ``project_id`` must be the same id the browser opened
    ``/api/projects/{id}/events`` with — the bus keys on it verbatim, so a
    short_id here and a UUID there is a stream nobody is listening to.

    Returns ``None`` when there is no project to narrate to — a CLI run
    against a fixture has no browser watching it, and handing the
    orchestrator a sink that publishes into nothing is more machinery
    than saying so.
    """
    if not project_id:
        return None
    pid = str(project_id)

    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

    def emit(evt: dict) -> None:
        payload = {"type": "office", "office": evt}
        if loop is None:
            publish_nowait(pid, payload)
            return
        try:
            # Safe from the loop thread too — it just runs on the next tick,
            # and the office is a live picture, not a transaction.
            loop.call_soon_threadsafe(publish_nowait, pid, payload)
        except RuntimeError:
            # The loop closed while the run was still going (client gone,
            # server shutting down). The run is what matters; drop the frame.
            log.debug("office_sink: loop closed, dropped %s", evt.get("type"))

    return OfficeNarrator(emit)
