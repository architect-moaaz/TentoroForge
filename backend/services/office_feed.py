"""The Foundry's one source: every job a project runs, as its agents doing it.

The Foundry used to hear only about a build the browser was streaming, through
the build panel's bridge: Smith's turns and fixes, the checks after a build,
the process trials, a publish and a self-heal moved no one, and a build started
in the background or picked up after a restart was never shown at all. Every
long job now keeps a run ledger (`services.blueprint.run_ledger`), so the
Foundry follows those: one reader of what the work itself records.

`ProjectFeed` follows `<app>/.forge/runs/*.jsonl`. On connect it replays the
ledgers still open — the Foundry shows what is under way — and then reads each
new line as it is written, from any ledger, new ones included. Each ledger is
narrated by what it records (`run_ledger.ledger_kind`):

* a build or a check: `OfficeNarrator`, step by step — Bob, Todd, Leo… at their
  desks, Otto reviewing as each piece lands, Tess and Trey on the checks;
* a turn, a fix or a self-heal: Smith, working, saying the step he is on;
* a publish: Dex, until the app is live.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from services.office_events import (OfficeNarrator, _short, agent_complete_event, agent_error_event,
                                    agent_start_event, agent_status_event)

#: A ledger open and written within this long is replayed on connect.
OPEN_WITHIN_S = 6 * 3600

#: Who does a run that keeps no steps, and what they are doing.
_RUN_AGENT = {"turn": "smith", "fix": "smith", "heal": "smith", "publish": "deployment", "drafts": "researcher"}
_RUN_DOING = {
    "turn": "Working on your message",
    "fix": "Looking into what went wrong",
    "heal": "Fixing a fault the app reported",
    "publish": "Publishing the app",
    "drafts": "Studying the references",
}
_RUN_DONE = {"turn": "Done", "fix": "Fixed", "heal": "Fixed", "publish": "Live", "drafts": "Drafts ready"}


class RunNarrator:
    """A run that is one agent's whole job (a turn, a fix, a publish)."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.agent = _RUN_AGENT.get(kind, "smith")

    def translate(self, line: dict) -> list[dict]:
        ev = str(line.get("event") or "")
        if ev == "run:start":
            return [agent_start_event(self.agent),
                    agent_status_event(self.agent, _RUN_DOING.get(self.kind, "Working"), progress=0.0)]
        if ev == "turn:step" and line.get("text"):
            return [agent_status_event(self.agent, _short(line.get("text")))]
        if ev == "run:end":
            return [agent_complete_event(self.agent),
                    agent_status_event(self.agent, _RUN_DONE.get(self.kind, "Done"), progress=1.0)]
        if ev == "run:crashed":
            return [agent_error_event(self.agent, _short(line.get("error")) or "Stopped before it finished")]
        return []


class StepNarrator(OfficeNarrator):
    """A build or a check: the step narrator, except that only a build ends in
    a celebration — a check that passed is quietly done."""

    def __init__(self, kind: str) -> None:
        super().__init__(emit=lambda _e: None)
        self.kind = kind

    def _on_run_end(self, line: dict) -> list[dict]:
        if self.kind == "build":
            return super()._on_run_end(line)
        return []

    def _on_run_crashed(self, line: dict) -> list[dict]:
        if self.kind == "build":
            return super()._on_run_crashed(line)
        return []


def narrator_for(path: Path) -> RunNarrator | StepNarrator:
    from services.blueprint.run_ledger import ledger_kind
    kind = ledger_kind(path)
    return StepNarrator(kind) if kind in ("build", "check") else RunNarrator(kind)


def _ended(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 4096))
            tail = fh.read().decode("utf-8", "replace").strip().splitlines()
        last = json.loads(tail[-1]).get("event") if tail else ""
    except (OSError, ValueError):
        return True
    return last in ("run:end", "run:crashed")


class ProjectFeed:
    """Follow one project's ledgers. `poll()` returns the office events written
    since the last call; the first call replays what is still open."""

    def __init__(self, output_dir: str | Path) -> None:
        self.runs = Path(output_dir) / ".forge" / "runs"
        self._offsets: dict[Path, int] = {}
        self._narrators: dict[Path, RunNarrator | StepNarrator] = {}
        self._partial: dict[Path, bytes] = {}
        self._started = False

    def _ledgers(self) -> list[Path]:
        try:
            return sorted(self.runs.glob("*.jsonl"))
        except OSError:
            return []

    def poll(self) -> list[dict]:
        out: list[dict] = []
        now = time.time()
        for path in self._ledgers():
            if path not in self._offsets:
                if not self._started:
                    # ON CONNECT: what is still under way is replayed from its
                    # start; what has ended is history, read from its end.
                    try:
                        recent = now - path.stat().st_mtime < OPEN_WITHIN_S
                    except OSError:
                        continue
                    if not recent or _ended(path):
                        try:
                            self._offsets[path] = path.stat().st_size
                        except OSError:
                            pass
                        continue
                self._offsets[path] = 0
                self._narrators[path] = narrator_for(path)
            out.extend(self._read(path))
        self._started = True
        return out

    def _read(self, path: Path) -> list[dict]:
        try:
            with path.open("rb") as fh:
                fh.seek(self._offsets[path])
                data = fh.read()
        except OSError:
            return []
        if not data:
            return []
        self._offsets[path] += len(data)
        data = self._partial.pop(path, b"") + data
        lines = data.split(b"\n")
        if lines and lines[-1]:
            self._partial[path] = lines.pop()             # a line still being written
        narrator = self._narrators.get(path) or narrator_for(path)
        self._narrators[path] = narrator
        out: list[dict] = []
        for raw in lines:
            if not raw.strip():
                continue
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            try:
                out.extend(narrator.translate(line))
            except Exception:  # noqa: BLE001 — one odd line never stops the Foundry
                continue
        return out


__all__ = ["OPEN_WITHIN_S", "ProjectFeed", "RunNarrator", "StepNarrator", "narrator_for"]
