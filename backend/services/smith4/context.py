"""The first page the loop is shown.

Not the whole application — `services.smith.context` argues the budget and it
is right: 80k tokens of JSON on every step is what makes a conversation cost
more than the work. The resolver's slice is the OPENING page; `read_section`,
`read_page_code` and `grep` are how the loop turns to any other. What is added
here is the state a turn carries between turns — the ask that was held while
Smith asked a question, the plan that was agreed to, the yes that a cascade is
waiting on — because a loop that cannot see those will ask for them again.
"""
from __future__ import annotations

from services.smith import plan as plan_mod
from services.smith_blueprint import Blueprint
from services.smith_blueprint_context import blueprint_to_context, pick_relevant_slice


def defined(output_dir: str) -> bool:
    """Whether there is an application to reason over — requirements or
    pages, the same test the Blueprint router makes."""
    from pathlib import Path
    current = Path(output_dir) / ".forge" / "blueprint" / "current.json"
    if not current.is_file():
        return False
    try:
        from services.blueprint.service import BlueprintService
        doc = BlueprintService.load(output_dir=str(output_dir)).doc
        return bool(doc.get("requirements") or doc.get("pages"))
    except Exception:  # noqa: BLE001 — unreadable is undefined
        return False


def opening(project_id: str, output_dir: str, ask: str, *, brief: str = "") -> str:
    """The Blueprint slice for `ask`, with the turn-to-turn state on top.

    Before there is an application the slice is empty and the page says so:
    what the person has said so far IS the application, and the moves that
    apply are `open_decisions` and `define_application`, not the verbs."""
    if not defined(output_dir):
        return ("THERE IS NO APPLICATION YET. Nothing is defined, so there is nothing to "
                "change, read or compose: the verbs below do not apply. What the person has "
                "said so far is the brief:\n\n" + (brief.strip() or "(nothing yet)")
                + "\n\nRead `open_decisions` to see what it leaves unsaid; ask ONE of them "
                "with `ask_user` and its chips; when nothing is open, `define_application`. "
                "Do not ask what the brief already answers.")
    bp = Blueprint.load(project_id=project_id, output_dir=output_dir)
    page = blueprint_to_context(pick_relevant_slice(bp, ask=ask))
    # WHAT IS RUNNING, FROM THE LEDGER, NOT FROM MEMORY. A status answer
    # built from the last check claimed fixes "in progress" while nothing
    # ran (pcn4owv7, 2026-10-15). This turn is itself the thing running, so
    # the line is about anything else: a build, a check, a turn that was lost.
    try:
        from services.run_registry import live_state
        page = ("LIVE STATE (answer any question about progress, status or time from this line, never "
                "from the last check; when nothing is running, say so): " + live_state(output_dir)
                + "\n\n" + page)
    except Exception:  # noqa: BLE001 — the page stands without the line
        pass
    waiting = plan_mod.peek(output_dir) if plan_mod.is_agreed(output_dir) else []
    if waiting:
        page = ("STEPS OF AN AGREED PLAN STILL WAITING (each is a later turn, done when they say "
                "`next`; do not do them now, and do not put them in a plan you propose for this "
                "message — they are already planned):\n" + "\n".join(f"- {s}" for s in waiting)
                + "\n\n" + page)
    return page


__all__ = ["defined", "opening"]
