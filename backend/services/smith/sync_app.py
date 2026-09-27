"""Bring the running application back in step with its definition.

The Blueprint is what the application IS; the files under `app/` are what it
was last written out as. Every change writes both, so they agree — until they
do not: a change whose seam re-projected too little, a platform fix that
changed what a projection writes, a file edited by hand. Then the person sees
one thing and Smith, reading the definition, sees another, and there is no
change for Smith to make: the definition already says what was asked.

Test2, 2026-09-28: Location Explorer was public in the Blueprint and still
served from the signed-in area, off the public menu. "Make Location Explorer
public" found nothing to change; "I still cannot see it in the menu" found
the page in the menu files it read. Smith gave up twice with "I could not
turn that into a change I am sure of" — the right answer was to write the
application out again from what it already says.

Deterministic: every projection, as an undo runs them (`reproject`), and a
report of what actually moved — files compared before and after, so "nothing
was out of step" is said when it is true rather than a list of every file
rewritten identically.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Where the projections write. Dependencies and build output are not the
#: application's definition and are not read.
_WATCHED = ("src", "public")
_SKIP = ("node_modules", ".next", ".forge-check", ".forge-look")


def _fingerprint(app_root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for top in _WATCHED:
        base = app_root / top
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or any(part in _SKIP for part in f.parts):
                continue
            try:
                out[str(f.relative_to(app_root))] = hashlib.sha1(f.read_bytes()).hexdigest()
            except OSError:
                continue
    return out


def sync(svc: Any, app_root: str) -> dict:
    """Write every projection from `svc.doc`; what changed, added and went."""
    from services.smith.reproject import everything

    from services.blueprint.schema_push import push_now

    root = Path(app_root)
    before = _fingerprint(root)
    everything(svc, app_root)
    after = _fingerprint(root)
    changed = sorted(k for k in after if k in before and before[k] != after[k])
    added = sorted(k for k in after if k not in before)
    removed = sorted(k for k in before if k not in after)
    # THE DATABASE IS PART OF THE APPLICATION TOO. A record added before its
    # table could be created (Test2's Area) is in the schema files and not in
    # the database; bringing the app in step brings that in step as well.
    pushed = push_now(root)
    return {"changed": changed, "added": added, "removed": removed,
            "database": "in step" if pushed["applied"] else pushed["reason"]}


def summary_of(out: dict) -> str:
    moved = out["changed"] + out["added"] + out["removed"]
    db = out.get("database") or ""
    db_line = (" Its database schema is in step too." if db == "in step"
               else f" The database schema could not be brought in step now: {db}." if db else "")
    if not moved:
        return ("The application already matches its definition — nothing was out of step." + db_line
                + " If something still looks wrong, tell me what you see and where.")
    head = ", ".join(moved[:6]) + (f" and {len(moved) - 6} more" if len(moved) > 6 else "")
    return (f"The application was out of step with its definition, so I wrote it out again from "
            f"what it says: {len(moved)} file(s) brought back in line ({head}).{db_line} Reload the "
            f"preview to see it.")


def run(output_dir: str, *, reasoning: Any = None) -> dict:
    """The seam envelope: `{applied, diff_summary, edited_paths, reason}`."""
    from services.blueprint.service import BlueprintService
    from services.llm_client import tell

    app_root = Path(output_dir) / "app"
    if not (app_root / "package.json").is_file():
        return {"applied": False, "edited_paths": [],
                "reason": "The application has not been built yet, so there is nothing to bring in step."}
    try:
        svc = BlueprintService.load(output_dir=output_dir)
        tell(reasoning, "Writing the application out again from its definition.", "step")
        out = sync(svc, str(app_root))
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[sync_app] %s", output_dir)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    moved = out["changed"] + out["added"] + out["removed"]
    return {"applied": True, "edited_paths": moved, "diff_summary": summary_of(out), **out}


__all__ = ["run", "summary_of", "sync"]
