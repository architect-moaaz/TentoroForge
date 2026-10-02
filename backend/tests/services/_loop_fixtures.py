"""Fixtures the loop's tests share: a repo, a move that writes, a scripted chooser.

`_session` builds the old shape — an understanding plus a scripted chooser —
over the v4 front door: the understanding becomes the first step of the turn
(as the classifier's verdict used to be), and the chooser's steps follow it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from services.smith.loop import Observation
from services.smith_blueprint import Blueprint
from tests.services._front_door import IterationMove, SmithSession, as_first_step


def _repo(tmp_path: Path) -> Path:
    subprocess.check_call(["git", "init", "-q", str(tmp_path)])
    subprocess.check_call(["git", "-C", str(tmp_path), "config", "user.email", "t@t.t"])
    subprocess.check_call(["git", "-C", str(tmp_path), "config", "user.name", "T"])
    (tmp_path / "seed.txt").write_text("seed")
    subprocess.check_call(["git", "-C", str(tmp_path), "add", "."])
    subprocess.check_call(["git", "-C", str(tmp_path), "commit", "-qm", "seed"])
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()
    return tmp_path


def _understanding(**given: Any) -> dict:
    """What the old classifier returned, with only the keys a turn reads."""
    out = {"answer": "", "clarification_needed": "", "clarification_options": [],
           "asks": [], "verb": "rename", "route": "", "widgets": [],
           "target_file": "", "element_label": "", "new_value": "",
           "screen": given.get("target_file", ""),
           "entity": "", "change": "",
           "current_behavior": "was", "desired_behavior": "now", "field": {}}
    out.update(given)
    return out


class _Writes:
    """A move that really edits a file, so the ground-truth checks are real."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.calls: list[dict] = []

    def __call__(self, understanding: dict, output_dir: str):
        self.calls.append(dict(understanding))
        target = str(understanding.get("target_file") or "").strip()
        label = str(understanding.get("element_label") or "").strip()
        path = Path(output_dir) / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{{"label": "{label}"}}\n')
        return IterationMove(move_name=f"edit({target})", touched_paths=[target])


class _FindsNothing:
    """A move that reports it changed nothing — the `SMITH-VERBS.md` failure."""

    def __init__(self, then: Any):
        self.then = then
        self.calls = 0

    def __call__(self, understanding: dict, output_dir: str):
        self.calls += 1
        if self.calls == 1:
            return None
        return self.then(understanding, output_dir)


class _ClaimsWithoutWriting(_Writes):
    """Reports a change it did not make — git catches it. `claims` times,
    after which it writes for real, so a test can watch a recovery."""

    def __init__(self, tmp_path, *, claims: int = 99):
        super().__init__(tmp_path)
        self.claims = claims

    def __call__(self, understanding, output_dir):
        if len(self.calls) < self.claims:
            self.calls.append(dict(understanding))
            return IterationMove(move_name="claims a change",
                                 touched_paths=["src/ghost.json"])
        return super().__call__(understanding, output_dir)


class _Chooser:
    """A scripted next-step seam; records what it was shown."""

    def __init__(self, *steps: dict):
        self.steps = list(steps)
        self.seen: list[list[Observation]] = []
        self.histories: list[list] = []

    def __call__(self, ask: str, ctx: str, observations: list,
                 history: list | None = None) -> dict:
        self.seen.append(list(observations))
        self.histories.append(list(history or []))
        if not self.steps:
            return {"tool": "done", "args": {}, "why": ""}
        return self.steps.pop(0)


def _session(tmp_path: Path, *, understanding: dict, move: Any,
             chooser: Any = None) -> SmithSession:
    """The understanding is the turn's first step; the chooser's steps follow.

    A first step that is refused as a question sent to look is made again,
    the way the old front door's clarification stood until answered.
    """
    first = as_first_step(understanding)
    state = {"made": False}

    def choose(ask: str, page: str, observations: list, history: list | None = None) -> dict:
        if not state["made"]:
            if observations and observations[-1].status == "error" \
                    and observations[-1].tool == first["tool"]:
                # sent to look; the old front door's question stood — make it again
                if first["tool"] == "ask_user" and chooser is not None:
                    state["made"] = True
                    return chooser(ask, page, observations, history)
                return first
            if not observations:
                return first
            state["made"] = True
        if chooser is None:
            return {"tool": "done", "args": {}, "why": ""}
        return chooser(ask, page, observations, history)

    return SmithSession(project_id="p1", output_dir=str(tmp_path),
                        guards_fn=lambda _out: [], iteration_move_fn=move,
                        next_step_fn=choose)


def _rename(target: str, label: str) -> dict:
    return {"tool": "rename",
            "args": {"target_file": target, "element_label": label,
                     "new_value": label, "screen": target,
                     "current_behavior": "was", "desired_behavior": "now"},
            "why": f"rename {label}"}


__all__ = ["_repo", "_understanding", "_Writes", "_FindsNothing", "_ClaimsWithoutWriting",
           "_Chooser", "_session", "_rename"]
