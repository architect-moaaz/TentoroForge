"""Undo — the one thing that makes every other change safe to try.

`revert_last_patch` reverses the last git commit, and a Blueprint application's
repo has no commits, so on these projects there has been no working undo at
all. Everything else Smith offers asks a nervous person to type into a machine
they cannot back out of.

The material was already there. §91 versions the whole document and
`BlueprintService.commit` writes the PRE-change state to `versions/vN.json`
before every change, so the state before any recorded change is on disk. This
is the verb that reaches it.

WHAT "UNDO" MEANS HERE. Not a reverse patch — a restore. The document goes
back to how it stood before the most recent change, and every projection is
re-run so the application matches it. Said twice, it goes back two changes: the
second call skips the undo itself and restores the state before the change
before it, which is what a person means by pressing undo twice.

NOTHING IS LOST. The history is append-only: an undo is itself a change, with
its own entry saying what it reversed, so the audit trail keeps both the change
and its reversal — and an undo can itself be undone.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell
from services.smith.section_change import SectionChangeError

logger = logging.getLogger(__name__)

#: How an undo names itself in the history. It is read back by the next undo
#: (to step past it) and by a person reading the log, which is why it is a
#: sentence and not a flag — `changeHistory` entries take no extra fields.
UNDO_PREFIX = "undo: "


def _history(doc: dict) -> list[dict]:
    return [h for h in (doc.get("changeHistory") or []) if isinstance(h, dict)]


def undoable(doc: dict) -> dict | None:
    """The most recent change that has not already been undone, or None.

    Walking back, each undo CONSUMES the change below it — skipping only the
    undo entries themselves would hand the second "undo that" the change the
    first one just reversed, so undo would toggle between two states instead
    of stepping back through them.
    """
    pending = 0
    for entry in reversed(_history(doc)):
        if str(entry.get("userRequest") or "").startswith(UNDO_PREFIX):
            pending += 1
            continue
        if pending:
            pending -= 1
            continue
        return entry
    return None


def what_would_be_undone(doc: dict) -> str:
    """The ask the next undo would reverse, in the words it was asked in."""
    entry = undoable(doc) or {}
    return " ".join(str(entry.get("userRequest") or "").split())


def revert(svc: Any, *, app_root: str | None = None, reasoning: Any = None) -> dict:
    """Restore the document as it stood before the last change, and re-project."""
    entry = undoable(svc.doc)
    if entry is None:
        raise SectionChangeError(
            "There is nothing to undo — no change has been recorded against "
            "this application yet.")

    version = int(entry.get("version") or 0)
    # `commit` writes the BEFORE state under the version it superseded, so the
    # state before the change recorded as vN is the snapshot vN-1.
    target = svc.version_path(version - 1)
    if not Path(target).is_file():
        raise SectionChangeError(
            f"I cannot undo “{what_would_be_undone(svc.doc)}”: the state "
            "before it was not kept, so restoring it would be a guess. "
            "Ask me for the opposite change instead and I will make it.")

    before = svc.snapshot()
    try:
        restored = json.loads(Path(target).read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise SectionChangeError(
            f"The saved state for that change could not be read ({exc}), so I "
            "have changed nothing.") from exc

    undone = str(entry.get("userRequest") or "that change")
    svc.doc = restored
    # APPEND-ONLY. The restored document carries the history as it was then;
    # keeping the current one means the undo appears in the log rather than
    # erasing the change it reversed.
    svc.doc["changeHistory"] = list(before.get("changeHistory") or [])
    svc.doc["version"] = int(before.get("version") or version)
    svc.validate()
    svc.commit(
        user_request=f"{UNDO_PREFIX}{' '.join(undone.split())}",
        smith_interpretation=f"restore the application as it stood before v{version}",
        before=before,
        affected=[str(a) for a in (entry.get("affectedArtifacts") or [])],
    )
    tell(reasoning, f"Restored the application as it stood before “{undone}”.", "step")

    from services.smith import reproject
    files = reproject.everything(svc, app_root)
    return {"applied": True, "undone": undone, "version": int(svc.doc.get("version") or 0),
            "restored_from": version - 1, "next": what_would_be_undone(svc.doc),
            "edited_paths": files}


def history(svc: Any) -> dict:
    """The versions a person can see and go back to, newest first: each
    recorded change with what was asked, when, and whether the application as
    it stood right after it was kept (and so can be restored)."""
    current = int(svc.doc.get("version") or 1)
    kept = set(svc.versions())
    out = []
    for h in reversed(_history(svc.doc)):
        v = int(h.get("version") or 0)
        if v <= 0:
            continue
        out.append({"version": v, "at": h.get("at"),
                    "request": " ".join(str(h.get("userRequest") or "").split())[:300],
                    "interpretation": " ".join(str(h.get("smithInterpretation") or "").split())[:300],
                    "undo": str(h.get("userRequest") or "").startswith(UNDO_PREFIX) or
                            str(h.get("userRequest") or "").startswith(RESTORE_PREFIX),
                    "current": v == current,
                    "restorable": v != current and v in kept})
    return {"current": current, "versions": out}


#: How a restore names itself in the history, like an undo.
RESTORE_PREFIX = "restore: "


def restore_to(svc: Any, version: int, *, app_root: str | None = None, reasoning: Any = None) -> dict:
    """Bring the application back to how it stood at `version`, and re-project.

    The same restore as `revert`, at a version the person chose instead of
    the one before the last change: `versions/vN.json` is the document as it
    stood at version N. Append-only like an undo — the restore is itself a
    recorded change, and can be undone."""
    current = int(svc.doc.get("version") or 1)
    if version == current:
        raise SectionChangeError(f"The application is already at version {version}.")
    target = svc.version_path(version)
    if not Path(target).is_file():
        raise SectionChangeError(f"Version {version} was not kept, so it cannot be restored.")
    before = svc.snapshot()
    try:
        restored = json.loads(Path(target).read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise SectionChangeError(f"Version {version} could not be read ({exc}); nothing was changed.") from exc
    entry = next((h for h in _history(before) if int(h.get("version") or 0) == version), {})
    said = " ".join(str(entry.get("userRequest") or "").split())
    svc.doc = restored
    svc.doc["changeHistory"] = list(before.get("changeHistory") or [])
    svc.doc["version"] = current
    svc.validate()
    svc.commit(user_request=f"{RESTORE_PREFIX}back to version {version}" + (f" ({said[:120]})" if said else ""),
               smith_interpretation=f"restore the application as it stood at v{version}", before=before)
    tell(reasoning, f"Restored the application as it stood at version {version}.", "step")
    from services.smith import reproject
    files = reproject.everything(svc, app_root)
    return {"applied": True, "restored": version, "version": int(svc.doc.get("version") or 0),
            "edited_paths": files}


def summary_of(out: dict) -> str:
    """What the undo did, and what the next one would do."""
    lines = [f"Undone: **{out['undone']}**.",
             "",
             "The application is back as it stood before that change, and every "
             "screen, rule and table has been written out again to match."]
    if out.get("next"):
        lines += ["", f"Say `undo` again to also reverse **{out['next']}**."]
    return "\n".join(lines)


def run(output_dir: str, *, reasoning: Any = None) -> dict:
    """One undo from an `output_dir` — the shape a tool handler needs."""
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "this project has no Blueprint yet, so there is no "
                          "change to undo."}
    try:
        out = revert(svc, app_root=str(Path(output_dir) / "app"), reasoning=reasoning)
    except SectionChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a turn degrades, it does not crash
        logger.exception("[smith] undo failed")
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out.get("edited_paths") or [],
            "diff_summary": summary_of(out), "reason": "", **out}


__all__ = ["revert", "run", "summary_of", "undoable", "what_would_be_undone", "UNDO_PREFIX"]
