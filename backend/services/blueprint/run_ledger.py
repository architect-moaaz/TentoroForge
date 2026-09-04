"""What a run planned, what it did, and where it stopped — on disk, as it goes.

`RunReport` already records completed, failed, skipped and blocked nodes with
reasons. It lives in memory for the length of the call and is then gone: a run
that ends abnormally leaves no trace of itself at all.

Three times in one night a build stopped mid-DAG and the only way to ask what
happened was archaeology — file mtimes, socket tables, thread counts, and
inferring the last node from which Blueprint sections were missing. Each answer
took the better part of an hour and one of them was wrong: a run that had ended
was read as a run that was hung, and the fix proposed for it (a timeout on the
model client) would have changed nothing.

    present : apis, codeMap, data, database, pageLayouts, pages, workflows …
    missing : tests, decisions, runtime, deployment, dependencies
    → "somewhere around integration or testing", six hours later

The ledger answers that in one file read.

APPEND-ONLY, FLUSHED PER LINE. The failure this exists to describe is a process
that stops without warning, so anything buffered until the end is lost exactly
when it is wanted. Each event is one JSON object on its own line, written and
flushed as it happens; a truncated final line means the process died mid-write,
which is itself worth knowing.

NOT the run registry. `services.run_registry` answers "is something happening
right now" for a page that just loaded, in memory, and forgets. This is the
record that outlives the run.

WATCHABLE WHILE IT HAPPENS. A ledger takes an optional `observer`, and every
line written to disk is handed to it as it goes. That is how the virtual office
animates: it is a second reader of this same account, not a second account. One
call site per event, so a node outcome added here reaches the screen without
anyone remembering to emit it twice — which is exactly how a picture of a run
drifts from the run.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

#: One file per run under the project's own directory, so a ledger travels with
#: the output it describes rather than living in a log nobody exports.
LEDGER_DIR = ".forge/runs"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


class RunLedger:
    """Append-only record of one run.

    Every method is best-effort: a ledger that raises would take down the run
    it is describing, which is the opposite of the point. Failures to write are
    swallowed deliberately — the run is the work, this is the account of it.
    """

    def __init__(
        self,
        output_dir: str | Path,
        run_id: str,
        *,
        phase: str = "",
        observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.run_id = run_id
        self.path = Path(output_dir) / LEDGER_DIR / f"{run_id}.jsonl"
        self._observer = observer
        self._t0 = time.monotonic()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        self._write({"event": "run:start", "phase": phase, "at": _now(),
                     "pid": os.getpid()})

    # ── writing ─────────────────────────────────────────────────────────
    def _write(self, obj: dict[str, Any]) -> None:
        obj.setdefault("elapsedMs", int((time.monotonic() - self._t0) * 1000))
        obj.setdefault("runId", self.run_id)
        if self._observer is not None:
            # Before the write, not after: the disk write fsyncs, and a watcher
            # that only hears about a node once the page cache has been forced
            # is a watcher that is always one node behind.
            try:
                self._observer(obj)
            except Exception:  # noqa: BLE001 — same contract as the file write
                pass
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
                fh.flush()
                # The whole point is surviving a process that stops without
                # warning, and a flush only reaches the OS buffer.
                os.fsync(fh.fileno())
        except Exception:  # noqa: BLE001 — never break the run being recorded
            pass

    def planned(self, nodes: list[str], already: list[str] | None = None) -> None:
        """The plan, before anything runs.

        Written first so a run that dies in its opening seconds still says what
        it MEANT to do. "Which of the eighteen never started" is unanswerable
        without this, and it is the question every post-mortem opened with.
        """
        self._write({"event": "plan", "nodes": nodes, "total": len(nodes),
                     "alreadyComplete": already or [], "at": _now()})

    def node_start(self, key: str, subjects: int = 1) -> None:
        self._write({"event": "node:start", "node": key, "subjects": subjects,
                     "at": _now()})

    def node_done(self, key: str, artifacts: int = 0) -> None:
        self._write({"event": "node:done", "node": key, "artifacts": artifacts,
                     "at": _now()})

    def node_subject(self, key: str, subject: str, index: int, total: int,
                     ok: bool = True) -> None:
        """One artifact of a fanning-out node.

        "Which of the eighteen stopped it" was the question `node_failed`
        answered only in aggregate: a node that died on page twelve and one
        that died on page one left the same line. This is also what lets a
        watcher show progress through a node that takes eighteen model calls
        rather than a single silence.
        """
        self._write({"event": "node:subject", "node": key, "subject": subject,
                     "index": index, "total": total, "ok": ok, "at": _now()})

    def node_retry(self, key: str, subject: str, attempt: int, of: int,
                   reason: str) -> None:
        """A rejected proposal going round again (§103).

        Invisible before this: a node that succeeded on its second attempt and
        one that succeeded on its first were indistinguishable, so the cost of
        the retry loop could not be read off a run at all.
        """
        self._write({"event": "node:retry", "node": key, "subject": subject,
                     "attempt": attempt, "of": of,
                     "reason": str(reason)[:600], "at": _now()})

    def node_failed(self, key: str, reason: str) -> None:
        self._write({"event": "node:failed", "node": key,
                     "reason": str(reason)[:600], "at": _now()})

    def node_blocked(self, key: str, reason: str) -> None:
        self._write({"event": "node:blocked", "node": key,
                     "reason": str(reason)[:600], "at": _now()})

    def node_skipped(self, key: str, unmet: str) -> None:
        self._write({"event": "node:skipped", "node": key, "unmet": unmet,
                     "at": _now()})

    def finish(self, report: Any) -> None:
        """The outcome. Absent from a ledger means the run did not reach it."""
        self._write({
            "event": "run:end", "at": _now(),
            "completed": list(getattr(report, "completed", []) or []),
            "failed": list(getattr(report, "failed", []) or []),
            "blocked": list(getattr(report, "blocked", []) or []),
            "skipped": list(getattr(report, "skipped", []) or []),
            "failedBecause": dict(getattr(report, "failed_because", {}) or {}),
            # A node that STOPPED TO ASK, and what it is waiting to be told.
            # `blocked` recorded only names, so a run held by §17's clarification
            # threshold and a run that died looked identical in the one file
            # that outlives the process.
            "blockedBecause": dict(getattr(report, "blocked_because", {}) or {}),
            "skippedBecause": dict(getattr(report, "skipped_because", {}) or {}),
        })

    def crashed(self, exc: BaseException) -> None:
        """The run raised out of the orchestrator. This is the line that was
        missing every time: a build stopped and nothing anywhere said why."""
        self._write({"event": "run:crashed", "at": _now(),
                     "error": f"{type(exc).__name__}: {str(exc)[:600]}"})


# ── reading ─────────────────────────────────────────────────────────────

def read(output_dir: str | Path, run_id: str) -> list[dict]:
    """Every event of one run, in order. A truncated last line is dropped —
    that is a process that died mid-write, and the lines before it stand."""
    path = Path(output_dir) / LEDGER_DIR / f"{run_id}.jsonl"
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def runs(output_dir: str | Path) -> list[str]:
    """Run ids for a project, newest first."""
    d = Path(output_dir) / LEDGER_DIR
    try:
        return [p.stem for p in sorted(d.glob("*.jsonl"),
                                       key=lambda p: p.stat().st_mtime,
                                       reverse=True)]
    except OSError:
        return []


def explain(output_dir: str | Path, run_id: str | None = None) -> dict[str, Any]:
    """Where a run got to, and — if it is over — what stopped it.

    The question every post-mortem asked, answered from the file rather than
    from mtimes and missing Blueprint sections.

    A LIVE RUN AND A DEAD ONE ARE NOT DESCRIBED THE SAME WAY. Both leave nodes
    that started and never finished, and the first version called them
    `stoppedIn` regardless: four nodes running normally in a wave were reported
    as the place a healthy run had stopped. A diagnostic that reads "working"
    as "stopped" sends the next post-mortem exactly where the last one went
    wrong, which is the mistake this module exists to stop repeating.

    So `running` is either true or the run is over, and the unfinished nodes
    are named `inFlight` while it lives and `stoppedIn` once it cannot move.
    """
    ids = runs(output_dir)
    rid = run_id or (ids[0] if ids else None)
    if not rid:
        return {"found": False}

    events = read(output_dir, rid)
    planned: list[str] = []
    started: list[str] = []
    done: list[str] = []
    failed: dict[str, str] = {}
    ended: dict[str, Any] | None = None
    crashed: dict[str, Any] | None = None

    pid: int | None = None
    for e in events:
        kind = e.get("event")
        if kind == "run:start":
            pid = e.get("pid")
        if kind == "plan":
            planned = list(e.get("nodes") or [])
        elif kind == "node:start":
            started.append(e.get("node"))
        elif kind == "node:done":
            done.append(e.get("node"))
        elif kind in ("node:failed", "node:blocked"):
            failed[e.get("node")] = e.get("reason", "")
        elif kind == "run:end":
            ended = e
        elif kind == "run:crashed":
            crashed = e

    # A node that started and never finished is where the run stopped — the
    # single fact that took an hour to establish by hand, three times. But
    # only once the run is over; before that it is simply the work in hand.
    unfinished = [n for n in started if n not in done and n not in failed]

    # OVER, AND HOW WE KNOW. A run that ends records it. A run whose PROCESS
    # dies records nothing — which is the case this module exists for, and
    # "no end event" alone cannot tell the two apart.
    #
    # The pid is written at run:start, so liveness is a fact rather than a
    # timeout guessing at one. A pid that is gone cannot still be working.
    # (Reuse could in principle resurrect a dead run's number; on a local
    # single-host run that is remote, and the alternative — calling a run dead
    # because it has been quiet for N minutes — is a heuristic that would have
    # mislabelled `data_model` every single time it thought for nine.)
    over = bool(ended or crashed)
    if not over and pid:
        try:
            os.kill(pid, 0)          # signal 0: liveness only, no effect
        except ProcessLookupError:
            over = True              # the process is gone; so is the run
        except PermissionError:
            pass                     # alive, owned by someone else

    return {
        "found": True,
        "runId": rid,
        "running": not over,
        # How `over` was decided, because "the process is gone" and "the run
        # said it finished" are different facts and a reader should not have
        # to guess which one they are looking at.
        "endedBy": ("crash" if crashed else "outcome" if ended
                    else "process gone" if over else None),
        "planned": planned,
        "completed": done,
        "failed": failed,
        # Named for what they mean, so a caller cannot read a live wave as a
        # stall. Both keys always exist; the one that does not apply is empty.
        "inFlight": [] if over else unfinished,
        "stoppedIn": unfinished if over else [],
        # "Never started" is only a finding once nothing more can start.
        "neverStarted": ([n for n in planned if n not in started]
                         if over else []),
        # Not `planned - started`: a node can finish without this ledger having
        # seen it start (older runs, or a writer that missed the event), and
        # calling a finished node pending is worse than saying nothing.
        "pending": ([] if over else
                    [n for n in planned
                     if n not in started and n not in done and n not in failed]),
        "endedCleanly": bool(ended),
        "crashed": crashed,
        "events": len(events),
    }
