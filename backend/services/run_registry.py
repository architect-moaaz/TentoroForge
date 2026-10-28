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

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

#: project_id -> live snapshot. Written from the stream's `emit`, read by the
#: run endpoint. Single-process, single event loop: no lock needed, and one
#: would only hide a threading assumption that is not true here.
_RUNS: dict[str, dict[str, Any]] = {}


#: The file a person's Stop leaves beside the application's ledgers. A FILE,
#: not a flag in memory: the backend runs two workers, and the one that takes
#: the Stop is not necessarily the one running the build. Cleared when the
#: next build begins.
STOP_FILE = Path(".forge") / "runs" / "STOP"


def request_stop(project_id: str, output_dir: str | Path) -> None:
    """The person pressed Stop: the build in flight ends at its next step,
    the checks at their next page, and what is built is handed over."""
    path = Path(output_dir) / STOP_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    except OSError:
        pass
    run = _RUNS.get(str(project_id))
    if run is not None:
        run["cancel"] = True


def stop_requested(output_dir: str | Path) -> bool:
    return (Path(output_dir) / STOP_FILE).is_file()


def clear_stop(output_dir: str | Path) -> None:
    try:
        (Path(output_dir) / STOP_FILE).unlink()
    except OSError:
        pass


def begin(project_id: str, *, phase: str, output_dir: str | Path | None = None) -> None:
    """A run has started for this project. Replaces any previous entry — but
    keeps the checks still running after the last hand-over, which are
    another process's work and did not end because a turn began."""
    if output_dir is not None:
        clear_stop(output_dir)
    prior = _RUNS.get(str(project_id)) or {}
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
        **({"checks": prior["checks"]} if prior.get("checks", {}).get("active") else {}),
    }


def checking(project_id: str, *, phase: str = "checking") -> None:
    """The application is handed over and its checks are running: the panel
    says so without saying "building", and the input stays open."""
    run = _RUNS.setdefault(str(project_id), {"active": False, "status": "complete", "startedAt": time.time()})
    run["checks"] = {"active": True, "phase": phase, "startedAt": time.time(), "scorecard": {}}


def checks_done(project_id: str, status: str = "done") -> None:
    run = _RUNS.get(str(project_id))
    if run is None or not isinstance(run.get("checks"), dict):
        return
    run["checks"].update({"active": False, "phase": status, "endedAt": time.time()})


def turn_in_flight(output_dir: str | Path) -> bool:
    """Whether a person's Smith turn is working on this application now —
    the newest ledger is a turn's and still alive. The fix loop waits for it:
    two writers on one tree is how a repair undoes what the person asked for."""
    import glob
    import os
    runs = sorted(glob.glob(os.path.join(str(output_dir), ".forge", "runs", "*.jsonl")))
    turns = [p for p in runs if _is_turn(p)]
    if not turns:
        return False
    folded = _fold(turns[-1])
    return bool(folded and folded.get("active"))


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
    elif event == "scorecard":
        checks = run.get("checks") if isinstance(run.get("checks"), dict) else None
        if checks is not None:
            checks["scorecard"] = dict(data.get("summary") or {})
            if data.get("phase"):
                checks["phase"] = str(data["phase"])


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


def ledger_snapshot(output_dir: str | Path, *, turns: bool = True) -> dict[str, Any] | None:
    """The run as the project's ledgers on disk tell it — for a client whose
    poll landed on a worker that never saw the run.

    THE REGISTRY IS ONE PROCESS'S MEMORY AND THE BACKEND RUNS TWO. The
    worker running a build holds its entry; the other answers "idle" — so
    once the panel's stream was released (ten minutes into a long turn) a
    reload showed a build in flight as nothing at all (rafm22pm, 2026-09-25,
    17 of 28 steps done and "stuck"). The ledger is the durable record every
    worker can read; this folds it the way `note` folds the stream.

    A RUN STILL GOING OUTRANKS ONE THAT ENDED. A Smith turn writes its own
    ledger, and a build it starts writes a newer one that ends first — the
    turn goes on to say what was built. Reading only the newest reported
    the turn over while it was still talking. `turns=False` reads builds
    only: whether a build is in flight is not whether Smith is."""
    import glob
    import os

    from services.blueprint.run_ledger import ledger_kind

    runs = sorted(glob.glob(os.path.join(str(output_dir), ".forge", "runs", "*.jsonl")))
    # A publish, a self-heal or a Drafts Room run keeps a ledger too (so the
    # cutover gate waits for it); none of them is the run this panel follows.
    wanted = ("build", "check", "turn", "fix") if turns else ("build", "check")
    runs = [p for p in runs if ledger_kind(p) in wanted]
    if not runs:
        return None
    newest = _fold(runs[-1])
    if newest is None or newest.get("active"):
        return newest
    now = time.time()
    for path in reversed(runs[:-1]):
        try:
            if now - os.path.getmtime(path) > LEDGER_STALE_S:
                continue
        except OSError:
            continue
        going = _fold(path)
        if going and going.get("active"):
            if not newest.get("nodesTotal"):
                return going
            # The build's steps, the turn's liveness.
            out = {**newest, "active": True, "status": "running"}
            out.pop("endedAt", None)
            out["elapsedMs"] = going.get("elapsedMs", out.get("elapsedMs"))
            return out
    return newest



def work_in_flight(output_dir: str | Path) -> bool:
    """Whether a build, a check or a Smith turn is working on the application
    now — a ledger of its that has not ended and is not stale."""
    import glob
    import os
    runs = sorted(glob.glob(os.path.join(str(output_dir), ".forge", "runs", "*.jsonl")))
    return any((_fold(path) or {}).get("active") for path in runs[-6:])


def live_state(output_dir: str | Path) -> str:
    """Where the work on this application stands RIGHT NOW, read off the
    ledgers on disk — the one thing a status answer may be built on.

    Asked "what is the % completion now", Smith answered "65–70%, fixes in
    progress" from the last check while nothing at all was running: the turn
    it described had been killed by the host forty minutes earlier (pcn4owv7,
    2026-10-15). Every status answer starts from this line."""
    import glob
    import os
    runs = sorted(glob.glob(os.path.join(str(output_dir), ".forge", "runs", "*.jsonl")))
    if not runs:
        return "NOTHING HAS RUN on this application yet."
    going = None
    for path in reversed(runs[-6:]):
        folded = _fold(path)
        if folded and folded.get("active"):
            going = (path, folded)
            break
    def kind_of(path: str) -> str:
        from services.blueprint.run_ledger import ledger_kind
        return {"check": "check of the application", "fix": "fix", "heal": "fix", "publish": "publish",
                "drafts": "Drafts Room run"}.get(ledger_kind(path), ledger_kind(path))
    def clock(epoch: float | None) -> str:
        return time.strftime("%H:%M UTC", time.gmtime(epoch)) if epoch else "?"
    if going is not None:
        path, folded = going
        started = folded.get("startedAt")
        minutes = int(max(0.0, time.time() - (started or time.time())) // 60)
        try:
            alive = clock(os.path.getmtime(path))
        except OSError:
            alive = "?"
        step = str(folded.get("step") or "")
        return (f"RIGHT NOW: a {kind_of(path)} is running — started {clock(started)}, {minutes} min so far, "
                f"last sign of life {alive}." + (f" Last step: {step}." if step else ""))
    path = runs[-1]
    folded = _fold(path) or {}
    ended = folded.get("endedAt")
    if folded.get("status") == "error":
        return (f"NOTHING IS RUNNING NOW. The last {kind_of(path)} was stopped by a platform restart at "
                f"{clock(ended)} before it finished; say “carry on” to pick it up.")
    return f"NOTHING IS RUNNING NOW. The last {kind_of(path)} ended at {clock(ended)}."


def last_build(output_dir: str | Path) -> dict[str, Any] | None:
    """The newest build run (not a turn, not a check), folded, whatever state
    it is in — the record a "continue" or "rerun" is answered from."""
    import glob
    import os
    runs = sorted(glob.glob(os.path.join(str(output_dir), ".forge", "runs", "*.jsonl")))
    for path in reversed(runs):
        from services.blueprint.run_ledger import ledger_kind
        if ledger_kind(path) != "build":                 # a turn, a check, a publish, a fix: not a build to resume
            continue
        return _fold(path)
    return None


def dead_build(output_dir: str | Path) -> dict[str, Any] | None:
    """The last build when it stopped short — its process went away, or it
    ended with a step failed or paused — and nothing is running now. None
    when the last build finished, is still going, or there was none.

    Eight asks in two weeks were "continue", "resume", "rerun" or "Build app"
    typed after such a build (fyuhs16i, qpqhdugb, 97l5iqsp, grpz7rl5,
    23libgx8, fnocleub, 20nhpelj): they were answered with the card to press,
    or with nothing. The record of what stopped was on disk the whole time."""
    run = last_build(output_dir)
    if not run or run.get("active"):
        return None
    if run.get("status") == "error":
        return run
    if run.get("failedNodes") or run.get("pausedBecause"):
        return run
    return None


def stopped_line(run: dict[str, Any]) -> str:
    """Where a build stopped and why, in one line, from its ledger."""
    def clock(epoch: Any) -> str:
        return time.strftime("%H:%M UTC", time.gmtime(float(epoch))) if epoch else "?"
    where = str(run.get("stage") or "")
    failed = list(run.get("failedNodes") or [])
    why = str(run.get("error") or run.get("pausedBecause") or "")
    if failed:
        why = f"{', '.join(failed[:3])} did not finish" + (f" ({why})" if why else "")
    done, total = int(run.get("nodesDone") or 0), int(run.get("nodesTotal") or 0)
    progress = f", {done} of {total} steps done" if total else ""
    return (f"The build that started at {clock(run.get('startedAt'))} stopped at {clock(run.get('endedAt'))}"
            + (f" at step {where}" if where else "") + progress
            + (f" — {why}" if why else "") + ".")


def _process_started(pid: int) -> float | None:
    """When process `pid` began (epoch seconds), or None when there is no
    such process or it cannot be read (outside Linux)."""
    try:
        ticks = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19])
        boot = next(int(line.split()[1]) for line in open("/proc/stat") if line.startswith("btime "))
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except Exception:  # noqa: BLE001
        return None


def _writer_alive(path: Path) -> bool:
    """Whether the process that opened this ledger is still running: the pid
    its `run:start` names exists, and began before the run did (a pid is
    reused by a new process after a restart)."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            first = json.loads(fh.readline() or "{}")
        pid = int(first.get("pid") or 0)
    except (OSError, ValueError, TypeError):
        return False
    if pid <= 0 or pid == os.getpid():
        return False
    began = _process_started(pid)
    if began is None:
        return False
    run_started = _epoch(first.get("at")) or 0.0
    return began <= run_started + 1


def _tail_event(fh: Any) -> str | None:
    fh.seek(0, os.SEEK_END)
    size = fh.tell()
    fh.seek(max(0, size - 4096))
    tail = fh.read().decode("utf-8", "replace").strip().splitlines()
    try:
        return str(json.loads(tail[-1]).get("event") or "") if tail else None
    except ValueError:
        return None


def close_once(path: str | Path, record: dict, *, still_open: Callable[[Path], bool] = lambda p: True) -> bool:
    """Append `record` to a ledger that has not ended — once, whoever asks.

    BOTH WORKERS CLOSE WHAT A RESTART KILLED, at the same moment, and each
    appended its own `run:crashed`: forge-v3's crashed ledgers carry the line
    twice, and the person was told twice (2026-10-26). The ledger is locked,
    its last line read again under the lock, and `still_open(path)` asked
    there (the writer is gone; the pulse has stopped) before anything is
    written. True only for the caller that wrote."""
    path = Path(path)
    try:
        fh = path.open("a+b")
    except OSError:
        return False
    try:
        try:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass                                          # no flock here: the check below still narrows it
        last = _tail_event(fh)
        if last is None or last in ("run:end", "run:crashed"):
            return False
        if not still_open(path):
            return False
        fh.seek(0, os.SEEK_END)
        fh.write((json.dumps(record) + "\n").encode("utf-8"))
        fh.flush()
        return True
    except OSError:
        return False
    finally:
        fh.close()                                        # closing releases the lock


def close_orphaned_ledgers(root: str | Path) -> list[str]:
    """A RESTART CLOSES WHAT IT KILLED. Every ledger is written by this
    process; one still open when the process starts belonged to the one
    before, and nothing it recorded is going to end. Left open, the panel
    read a killed engineer build as "Building…" for three minutes after
    the restart and took no Build press (Ecom L1, 2026-10-11). Each is
    closed with `run:crashed`, which is what a poll would have found later.
    Returns the ids closed."""
    closed: list[str] = []
    root = Path(root)
    if not root.is_dir():
        return closed
    for runs in root.glob("*/.forge/runs"):
        for path in runs.glob("*.jsonl"):
            # A WORKER RESTARTING IS NOT THE PLATFORM RESTARTING. The backend
            # runs two workers; when one is replaced, the other's runs — and
            # the checks a separate process runs — go on. Closed here, Personal
            # Finance's checks, alive and heartbeating, were told to its owner
            # as lost (u8w3uw4j, 2026-10-22): `_writer_alive` keeps them open.
            if close_once(path, {"event": "run:crashed", "error": "the platform restarted while it ran",
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                          still_open=lambda p: not _writer_alive(p)):
                closed.append(path.stem)
                CLOSED_PATHS.append(str(path))
    return closed


#: The turn ledgers alive in this process, by the application's folder.
TURNS: dict[str, Any] = {}


def turn_step(output_dir: str | Path, text: str) -> None:
    """The step a turn is on, written to its ledger if one is registered
    for this application in this process. Nothing when there is none."""
    ledger = TURNS.get(str(Path(output_dir).resolve()))
    if ledger is not None:
        try:
            ledger.step(text)
        except Exception:  # noqa: BLE001 — a note, never the turn
            pass


#: Every ledger `close_orphaned_ledgers` closed in this process, by path —
#: so the person whose turn it was can be told (`main._tell_whose_turn_was_lost`).
CLOSED_PATHS: list[str] = []


def _is_turn(path: str | Path) -> bool:
    from services.blueprint.run_ledger import TurnLedger
    return Path(path).stem.endswith(TurnLedger.SUFFIX)


def _fold(path: str) -> dict[str, Any] | None:
    """One ledger folded into a snapshot."""
    import json
    import os

    run: dict[str, Any] = {"active": False, "status": "idle", "phase": "", "stage": None,
                           "nodesDone": 0, "nodesTotal": 0, "callsDone": 0, "nodes": [], "moments": [],
                           "awaitingApproval": False, "source": "ledger", "runId": Path(path).stem}
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
                elif ev == "turn:step":
                    run["step"] = str(e.get("text") or "")
                    run["stepAt"] = _epoch(e.get("at"))
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
        # HOW IT ENDED, KEPT. A run that ended with a node failed or paused
        # was "complete" to every reader; the person was told to press Build
        # again with no word of what stopped it (fnocleub, grpz7rl5, 2026-10).
        run["failedNodes"] = [str(x) for x in (last.get("failed") or []) if x] if last.get("event") == "run:end" else []
        run["pausedBecause"] = str(last.get("pausedBecause") or "")
        if last.get("event") == "run:crashed":
            run["error"] = str(last.get("error") or run.get("error") or "its process went away")
    elif age > LEDGER_STALE_S:
        run["status"] = "error"
        if _is_turn(path):
            run["interrupted"] = True
            run["error"] = ("Smith stopped partway through that request — the server process "
                            "working on it went away. Send it again and Smith picks it up.")
        else:
            run["error"] = "the run stopped without ending — its process is gone"
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

    checks = run.get("checks") if isinstance(run.get("checks"), dict) else None
    if not run.get("active") and not (checks and checks.get("active")):
        if time.time() - float(run.get("endedAt") or checks and checks.get("endedAt") or 0) > 120:
            _RUNS.pop(str(project_id), None)
            return {"active": False, "status": "idle"}

    out = dict(run)
    out["elapsedMs"] = int((time.time() - float(run["startedAt"])) * 1000)
    if checks and checks.get("active") and not run.get("active"):
        # THE BUILD ENDED, THE CHECKS GO ON. Said as its own phase, never as
        # "running": a panel that reads this must not say "Building…" over an
        # application that is handed over and in use.
        out["phase"] = "checking"
    return out
