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


class Busy(RuntimeError):
    """Another engineer is at work on this app."""


class Journal:
    """`.forge/engineer/journal.jsonl`: one JSON object per line, in order."""

    def __init__(self, output_dir: str | Path):
        self.dir = Path(output_dir) / ".forge" / "engineer"
        self.path = self.dir / "journal.jsonl"
        self.lock = self.dir / "lock"

    def write(self, event: str, **data: Any) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        row = {"event": event, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **data}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        return row

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
        for r in self.rows():
            if r.get("event") == "feature:done" and r.get("feature") and r["feature"] not in out:
                out.append(str(r["feature"]))
        return out

    def last(self, event: str) -> dict | None:
        found = None
        for r in self.rows():
            if r.get("event") == event:
                found = r
        return found

    # --- one engineer per app -------------------------------------------
    def acquire(self) -> None:
        """Take the app, or raise `Busy` naming who has it. A lock whose
        holder is gone is taken over."""
        self.dir.mkdir(parents=True, exist_ok=True)
        holder = self._holder()
        if holder and _alive(holder):
            raise Busy(f"an engineer (pid {holder}) is already at work on this app")
        self.lock.write_text(str(os.getpid()), "utf-8")

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
