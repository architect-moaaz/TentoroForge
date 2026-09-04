"""Which runs are in flight, so a reloaded page can find one.

A run's progress lived only in the SSE stream that carried it. The Blueprint
records what a run WROTE, and the conversation records what Smith SAID, but
nothing recorded that a run was happening — so closing the tab, losing the
session, or simply reloading left the panel with no way to discover a build
already under way. It rendered an idle project on top of a working DAG, and
the only honest signals were the backend's CPU and its open sockets.

That is the same shape as the empty editor panels: doing nothing and doing
something look identical to whoever arrives late.

IN MEMORY, DELIBERATELY. The DAG runs as a detached asyncio task in this
process; if the process goes, the run goes with it. A registry that outlived
the work it describes would report runs that no longer exist, which is worse
than reporting none — it is the same lie in the other direction. Registry and
run share a lifetime.

This is not the run ledger. A ledger records which nodes were meant to run and
which did, and survives to be audited afterwards. This answers one question —
"is something happening right now, and how far along" — and forgets.
"""

from __future__ import annotations

import time
from typing import Any

#: project_id -> live snapshot. Written from the stream's `emit`, read by the
#: run endpoint. Single-process, single event loop: no lock needed, and one
#: would only hide a threading assumption that is not true here.
_RUNS: dict[str, dict[str, Any]] = {}


def begin(project_id: str, *, phase: str) -> None:
    """A run has started for this project. Replaces any previous entry."""
    _RUNS[str(project_id)] = {
        "active": True,
        "phase": phase,
        "startedAt": time.time(),
        "stage": None,
        "nodesDone": 0,
        "nodesTotal": 0,
        "awaitingApproval": False,
        "status": "running",
    }


def note(project_id: str, event: str, data: dict[str, Any]) -> None:
    """Fold one stream event into the snapshot.

    Mirrors the events the panel already reduces, so a reattached client sees
    the same numbers it would have accumulated had it watched throughout.
    """
    run = _RUNS.get(str(project_id))
    if run is None:
        return

    if event == "plan":
        nodes = data.get("nodes")
        if isinstance(nodes, list):
            run["nodesTotal"] = len(nodes)
    elif event == "node:start":
        run["stage"] = data.get("label") or data.get("node") or run.get("stage")
    elif event == "node:done":
        run["nodesDone"] = run.get("nodesDone", 0) + 1
    elif event == "done":
        # §25 — the approval gate is a pause, not an end. A client arriving
        # here must see a decision waiting rather than a run in progress.
        #
        # Read from `done`, which carries the flag the panel itself uses. It
        # was inferred from any message carrying `options`, and Smith's §16
        # clarifying questions carry options too — so asking which language to
        # use was reported as a definition waiting to be approved, twenty
        # seconds into a run with nothing yet to approve.
        if data.get("awaitingApproval"):
            run["awaitingApproval"] = True
        finish(project_id, "complete")
    elif event == "error":
        finish(project_id, "error", detail=str(data.get("message") or "")[:400])


def finish(project_id: str, status: str, *, detail: str | None = None) -> None:
    """The run ended. Kept briefly so a client that reloads at the finish line
    sees an outcome rather than silence."""
    run = _RUNS.get(str(project_id))
    if run is None:
        return
    run["active"] = False
    run["status"] = status
    run["endedAt"] = time.time()
    if detail:
        run["error"] = detail


def snapshot(project_id: str) -> dict[str, Any]:
    """What to tell a client that just loaded the page.

    A finished run is reported for a couple of minutes and then forgotten —
    long enough to survive a reload at the finish line, short enough that a
    stale "complete" is never mistaken for this visit's run.
    """
    run = _RUNS.get(str(project_id))
    if run is None:
        return {"active": False, "status": "idle"}

    if not run.get("active"):
        if time.time() - float(run.get("endedAt") or 0) > 120:
            _RUNS.pop(str(project_id), None)
            return {"active": False, "status": "idle"}

    out = dict(run)
    out["elapsedMs"] = int((time.time() - float(run["startedAt"])) * 1000)
    return out
