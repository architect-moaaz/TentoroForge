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
        "callsDone": 0,
        #: The plan's nodes in order, each with the state the panel draws —
        #: so a reloaded page gets its rows back, not just a count.
        "nodes": [],
        "awaitingApproval": False,
        "status": "running",
    }


#: The events the level map is drawn from — kept, bounded, so a page that
#: loads mid-build gets the map back rather than a count. Small each (a
#: score, an id, the first problems), never a picture.
MOMENTS = frozenset({"node:subject", "observer:verdict", "observer:repair", "observer:unrepaired",
                     "node:retry", "node:stalled", "run:paused", "page:look"})
MOMENTS_KEPT = 600


def note(project_id: str, event: str, data: dict[str, Any]) -> None:
    """Fold one stream event into the snapshot.

    Mirrors the events the panel already reduces, so a reattached client sees
    the same numbers it would have accumulated had it watched throughout.
    """
    run = _RUNS.get(str(project_id))
    if run is None:
        return
    if event in MOMENTS:
        kept = run.setdefault("moments", [])
        kept.append({"event": event, **{k: v for k, v in data.items() if k != "at"}})
        if len(kept) > MOMENTS_KEPT:
            del kept[:len(kept) - MOMENTS_KEPT]

    if event == "plan":
        nodes = data.get("nodes")
        if isinstance(nodes, list):
            run["nodesTotal"] = len(nodes)
            run["nodes"] = [{"key": str(k), "state": "waiting", "calls": 0}
                            for k in nodes]
    elif event == "node:start":
        run["stage"] = data.get("label") or data.get("node") or run.get("stage")
        _node(run, data)["state"] = "running"
    elif event == "node:subject":
        # One page of a fan-out finished; the node has not. The counts come
        # from the event — the stream's reader of the ledger already did the
        # arithmetic, and adding one here per subject is what reported a run
        # as 23 of 19.
        node = _node(run, data)
        node["calls"] = node.get("calls", 0) + 1
        if data.get("index") is not None and data.get("total"):
            node["subject"] = f"{data['index']} of {data['total']}"
        _counts(run, data)
    elif event == "node:done":
        node = _node(run, data)
        node["state"] = "done"
        node.pop("subject", None)
        _counts(run, data)
    elif event in ("node:failed", "node:blocked", "node:skipped"):
        _node(run, data)["state"] = "failed"
    elif event == "done":
        # A `timeout` done is the panel being RELEASED after a long turn, NOT the
        # run ending — the DAG carries on in the background. Finishing here marked
        # the run complete while it was still building, and a snapshot that reads
        # complete stops updating node states — so the run panel FROZE at whatever
        # node was current ("Page Design") and looked stuck. Ignore it; the real
        # `done` the background emits on completion is what finishes the run.
        if data.get("status") == "timeout":
            return
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


def _node(run: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """The snapshot's entry for the event's node, added if the plan never
    named it (a resumed run can start a node the plan line omitted)."""
    key = str(data.get("node") or "")
    for node in run.setdefault("nodes", []):
        if node.get("key") == key:
            return node
    node = {"key": key, "state": "waiting", "calls": 0}
    run["nodes"].append(node)
    return node


def _counts(run: dict[str, Any], data: dict[str, Any]) -> None:
    for key in ("nodesDone", "nodesTotal", "callsDone"):
        if isinstance(data.get(key), int):
            run[key] = data[key]


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


def active_projects() -> list[str]:
    """The projects with a turn in flight — a DAG running, or a chat turn
    still writing its answer after the DAG ended.

    THE LEDGER GOES QUIET BEFORE THE TURN DOES. A cutover's idle gate read
    each project's newest run ledger and took `run:end` as idle; the turn
    that had run that DAG was still composing its "here's what I understood"
    message when the container was recreated under it (i3i950po, 2026-09-25
    10:21 UTC), and the tester waited an hour for an answer that never came.
    This is what a gate asks instead of the ledger."""
    return sorted(pid for pid, run in _RUNS.items() if run.get("active"))


#: A ledger whose newest line is older than this, and not an end, is a run
#: whose process died: the heartbeat writes every 20 seconds.
LEDGER_STALE_S = 180


def ledger_snapshot(output_dir: str | Path) -> dict[str, Any] | None:
    """The run as the project's newest ledger on disk tells it — for a
    client whose poll landed on a worker that never saw the run.

    THE REGISTRY IS ONE PROCESS'S MEMORY AND THE BACKEND RUNS TWO. The
    worker running a build holds its entry; the other answers "idle" — so
    once the panel's stream was released (ten minutes into a long turn) a
    reload showed a build in flight as nothing at all (rafm22pm, 2026-09-25,
    17 of 28 steps done and "stuck"). The ledger is the durable record every
    worker can read; this folds it the way `note` folds the stream."""
    import glob
    import json
    import os

    runs = sorted(glob.glob(os.path.join(str(output_dir), ".forge", "runs", "*.jsonl")))
    if not runs:
        return None
    path = runs[-1]
    run: dict[str, Any] = {"active": False, "status": "idle", "phase": "", "stage": None,
                           "nodesDone": 0, "nodesTotal": 0, "callsDone": 0, "nodes": [], "moments": [],
                           "awaitingApproval": False, "source": "ledger"}
    started: str | None = None
    last: dict[str, Any] | None = None
    seen_subjects: set[str] = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                last = e
                ev = str(e.get("event") or "")
                if ev == "run:start":
                    started = e.get("at"); run["phase"] = e.get("phase") or ""
                    run["startedAt"] = _epoch(started)
                elif ev == "plan":
                    nodes = e.get("nodes") if isinstance(e.get("nodes"), list) else []
                    run["nodesTotal"] = len(nodes)
                    run["nodes"] = [{"key": str(k), "state": "waiting", "calls": 0} for k in nodes]
                    run["levels"] = e.get("levels")
                elif ev == "node:start":
                    run["stage"] = e.get("node"); _node(run, e)["state"] = "running"
                elif ev == "node:subject":
                    node = _node(run, e); node["calls"] = node.get("calls", 0) + 1
                    run["callsDone"] += 1; seen_subjects.add(str(e.get("node")))
                    if e.get("total"):
                        node["subject"] = f"{e.get('done') if e.get('done') is not None else e.get('index')} of {e['total']}"
                elif ev == "node:done":
                    node = _node(run, e); node["state"] = "done"; node.pop("subject", None)
                    run["nodesDone"] += 1
                    if str(e.get("node")) not in seen_subjects:
                        run["callsDone"] += 1
                elif ev in ("node:failed", "node:blocked", "node:skipped"):
                    _node(run, e)["state"] = "failed"
                if ev in MOMENTS:
                    run["moments"].append({"event": ev, **{k: v for k, v in e.items() if k not in ("at", "elapsedMs", "runId")}})
                    if len(run["moments"]) > MOMENTS_KEPT:
                        del run["moments"][:len(run["moments"]) - MOMENTS_KEPT]
    except OSError:
        return None
    if last is None:
        return None
    ended = str(last.get("event") or "") in ("run:end", "run:crashed")
    age = time.time() - os.path.getmtime(path)
    if ended:
        run["status"] = "complete" if last.get("event") == "run:end" else "error"
        run["endedAt"] = _epoch(last.get("at")) or os.path.getmtime(path)
        run["awaitingApproval"] = bool(last.get("awaitingApproval"))
    elif age > LEDGER_STALE_S:
        run["status"] = "error"; run["error"] = "the run stopped without ending — its process is gone"
    else:
        run["active"] = True; run["status"] = "running"
    run["elapsedMs"] = int(((run.get("endedAt") or time.time()) - (run.get("startedAt") or time.time())) * 1000)
    return run


def _epoch(at: Any) -> float | None:
    """An ISO `at` (UTC, `Z`) as seconds since the epoch."""
    if not at:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.strptime(str(at), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


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
