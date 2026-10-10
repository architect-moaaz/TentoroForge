"""The engineer's journal: a durable job.

A Smith turn had twenty steps, no clock, a reply written only at its end,
and nothing on disk between: when the process died (an out-of-memory kill,
a cutover) a finished fix was never reported, and "carry on" started from
nothing (E-commerce, 2026-10-09). The engineer's work is written down as it
goes — every feature begun and finished, every change landed, every proof —
so a run picks up where the last one stopped, a time budget ends a run with
what it proved and what is left, and one engineer works on an app at a time.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterator


#: A lock nothing has pulsed for this long is nobody's.
STALE_MINUTES = 5


class Busy(RuntimeError):
    """Another engineer is at work on this app."""


class Journal:
    """`.forge/engineer/journal.jsonl`: one JSON object per line, in order."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.dir = self.output_dir / ".forge" / "engineer"
        self.path = self.dir / "journal.jsonl"
        self.lock = self.dir / "lock"
        self._narrator: Any = None

    def write(self, event: str, **data: Any) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        row = {"event": event, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **data}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        self._narrate(row)
        return row

    def _narrate(self, row: dict) -> None:
        """THE OFFICE READS THE JOURNAL. The same row that is written down is
        the one the floor animates — Smith's steps, the engineer's features —
        through the project's office when one is bound (`office_bridge`);
        never fatal, and nothing when no browser is watching."""
        try:
            if self._narrator is None:
                from services.office_bridge import office_for
                from services.office_events import JournalNarrator
                show = office_for(self.output_dir)
                self._narrator = JournalNarrator(show) if show is not None else False
            if self._narrator:
                self._narrator(row)
        except Exception:  # noqa: BLE001 — a picture never breaks the work
            pass

    def rows(self) -> Iterator[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
        except FileNotFoundError:
            return

    def finished(self) -> list[str]:
        """The features a previous run finished, in order."""
        out: list[str] = []
        for r in self.finished_rows():
            if r["feature"] not in out:
                out.append(str(r["feature"]))
        return out

    def finished_rows(self) -> list[dict]:
        """Every `feature:done` row, in order — what each finished feature
        covered (its screens) and what it proved, for `build.proven_before`."""
        return [r for r in self.rows() if r.get("event") == "feature:done" and r.get("feature")]

    def last(self, event: str) -> dict | None:
        found = None
        for r in self.rows():
            if r.get("event") == event:
                found = r
        return found

    # --- one engineer per app -------------------------------------------
    def acquire(self) -> None:
        """Take the app, or raise `Busy` naming who has it. A lock whose
        holder is gone is taken over — and so is one whose holder is alive
        but whose build has not pulsed: in a container the pids are few and
        reused, and a killed resume's pid (Ecommerce1, 2026-10-10) is the
        next worker's tomorrow."""
        self.dir.mkdir(parents=True, exist_ok=True)
        holder = self._holder()
        if holder and _alive(holder) and self._pulsing():
            raise Busy(f"an engineer (pid {holder}) is already at work on this app")
        self.lock.write_text(str(os.getpid()), "utf-8")

    def _pulsing(self) -> bool:
        """Whether the engineer holding the lock is at work: the lock is
        fresh, or an engineer's ledger on this app pulsed within
        `STALE_MINUTES` (the pulse is every twenty seconds)."""
        try:
            latest = self.lock.stat().st_mtime
        except OSError:
            return False
        for ledger in (self.dir.parent / "runs").glob("*-engineer.jsonl"):
            try:
                latest = max(latest, ledger.stat().st_mtime)
            except OSError:
                continue
        return time.time() - latest < STALE_MINUTES * 60

    def release(self) -> None:
        if self._holder() == os.getpid():
            try:
                self.lock.unlink()
            except OSError:
                pass

    def _holder(self) -> int | None:
        try:
            return int(self.lock.read_text("utf-8").strip() or 0) or None
        except (OSError, ValueError):
            return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Budget:
    """A run's time, in minutes; `left()` is what remains, `over()` whether
    it is spent."""

    def __init__(self, minutes: float):
        self.minutes = float(minutes)
        self.started = time.monotonic()

    def spent(self) -> float:
        return (time.monotonic() - self.started) / 60.0

    def left(self) -> float:
        return max(self.minutes - self.spent(), 0.0)

    def over(self) -> bool:
        return self.minutes > 0 and self.spent() >= self.minutes


__all__ = ["Journal", "Budget", "Busy"]
