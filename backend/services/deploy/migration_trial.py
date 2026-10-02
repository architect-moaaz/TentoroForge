"""A publish tries its migration on a copy of the live data first.

The publish build migrates the live database in place: renames keep their
data, a new required field is filled first, a changed type is converted,
removed data is kept in `forge_retired.rows`. What would lose or corrupt
records — a value that will not become the new type, a required field with
nothing to fill it, duplicates under a new "must be unique" — is refused
before anything changes (`prepare-schema.ts`). Safe, but the refusal arrived
as a failed publish, and only from data the preview never had: the
customers' own records. Smith tries every schema change on the app's own
database (`schema_push.push_now`); the live one it never sees.

So, on a redeploy — there is live data — the publish first makes a Neon
branch (a copy-on-write copy of the live database, in seconds), runs the
build's own chain on it, and deletes it. A refusal goes to Smith,
unattended, in the chain's own words: the records it names are real people's
and are kept; the definition is changed so they fit (a default for the new
field, the type kept, the rule relaxed or the duplicates' meaning settled).
The trial runs again. Only a trial that passes lets the publish go on; one
that still refuses stops it before anything is uploaded, and the live app
keeps serving what it served.

A trial that cannot run (Neon unreachable, no branch) does not stop the
publish: the build's own prepare step still refuses rather than lose data.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: Rounds of trial → Smith → trial.
ROUNDS = 2
STEPS = 12


async def trial(neon: Any, project_id: str, app_root: str | Path, *,
                chain: Callable[..., dict] | None = None) -> dict:
    """The publish chain on a branch of the live database. ``{"ran", "ok",
    "reason", "lines"}`` — `ran` False when no copy could be made."""
    if chain is None:
        from services.blueprint.schema_push import run_chain as chain
    name = f"forge-trial-{int(time.time())}"
    try:
        branch = await neon.create_branch(project_id, name)
    except Exception as exc:  # noqa: BLE001 — no copy, no trial; the build still guards
        logger.warning("[migration-trial] no branch for %s: %s", project_id, exc)
        return {"ran": False, "ok": True, "reason": f"no copy of the live data could be made: {exc}", "lines": []}
    try:
        # As the publish runs it on a redeploy: the data is kept, never reset.
        out = await asyncio.to_thread(chain, app_root, branch["database_url"],
                                      extra_env={"FORGE_KEEP_DB_STATE": "1"})
        return {"ran": True, "ok": bool(out.get("applied")), "reason": str(out.get("reason") or ""),
                "lines": list(out.get("lines") or [])}
    finally:
        try:
            await neon.delete_branch(project_id, branch["branch_id"])
        except Exception:  # noqa: BLE001 — a leftover branch is housekeeping, not a failed publish
            logger.warning("[migration-trial] branch %s of %s not deleted", name, project_id, exc_info=True)


def fault_ask(reason: str, lines: list[str]) -> str:
    said = "\n".join(lines[-20:]) or reason
    return (
        "Publishing would change the live database, and on a copy of it the change was refused — "
        f"the live records do not fit the definition as it is now:\n{said}\n\n"
        "Those records are real people's and must all be kept: never delete or rewrite them. Where "
        "the cause is mechanical — a field that became required with nothing to fill it, a type the "
        "values will not convert to, a field the definition no longer matches — change the "
        "definition so they fit and make the app's own database take it too. But NEVER undo a rule "
        "the owner asked for (a name that must be unique, a value that is always given) to make "
        "their records fit it: that is theirs to settle. Then change nothing and end with `answer`: "
        "which records break which rule, and the choices (change those records in the app, or relax "
        "the rule). Nobody is waiting to answer questions now: decide from the definition and act."
    )


from services.blueprint.field_changes import field_settings, what_changed  # noqa: E402,F401


def _definition(output_dir: str | Path) -> dict:
    import json
    try:
        return json.loads((Path(output_dir) / ".forge" / "blueprint" / "current.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


async def ensure_publishable(neon: Any, project_id: str, output_dir: str | Path, *,
                             app_project_id: str = "",
                             run_turn: Callable[..., dict] | None = None,
                             chain: Callable[..., dict] | None = None,
                             say: Callable[[str], None] | None = None,
                             rounds: int = ROUNDS) -> dict:
    """``{"ok", "ran", "fixed", "reason"}`` — whether the live data will take
    this publish, after Smith has had `rounds` goes at what would not."""
    if run_turn is None:
        from services.smith4.platform import smith_result as run_turn
    say = say or (lambda _t: None)
    app_root = Path(output_dir) / "app"
    out = await trial(neon, project_id, app_root, chain=chain)
    fixed = False
    changed: list[str] = []
    for _round in range(rounds):
        if not out["ran"] or out["ok"]:
            break
        say("The live data would not take this change as it is — fixing the definition so every "
            "record is kept, then trying again.")
        before = _definition(output_dir)
        turn: dict = {}
        try:
            turn = await asyncio.to_thread(run_turn, app_project_id, str(output_dir),
                                           fault_ask(out["reason"], out["lines"]),
                                           max_steps=STEPS, unattended=True) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[migration-trial] repair turn failed: %s", exc)
        changed += what_changed(before, _definition(output_dir))
        if not turn.get("edited_paths"):
            # NOTHING CHANGED: it is the owner's to settle. Their words to read,
            # not another trial of the same definition.
            said = str(turn.get("answer") or turn.get("question") or "").strip()
            return {"ok": False, "ran": True, "fixed": False, "reason": said or out["reason"],
                    "lines": out["lines"], "changed": "; ".join(changed), "settle": said}
        out = await trial(neon, project_id, app_root, chain=chain)
        fixed = out["ok"]
    # WHAT WAS CHANGED TO FIT IS SAID. The owner asked for the rule; if the
    # live data made Smith settle it differently, they are told how.
    return {"ok": out["ok"], "ran": out["ran"], "fixed": fixed and out["ok"], "reason": out["reason"],
            "lines": out["lines"], "changed": "; ".join(changed), "settle": ""}
