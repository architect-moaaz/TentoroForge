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
        from services import project_templates
        staged = project_templates.pending(output_dir)
        if staged:
            return template_page(staged, brief)
        return ("THERE IS NO APPLICATION YET. Nothing is defined, so there is nothing to "
                "change, read or compose: the verbs below do not apply. What the person has "
                "said so far is the brief:\n\n" + (brief.strip() or "(nothing yet)")
                + "\n\nRead `open_decisions` to see what it leaves unsaid; ask ONE of them "
                "with `ask_user` and its chips; when nothing is open, `define_application`. "
                "Do not ask what the brief already answers.")
    bp = Blueprint.load(project_id=project_id, output_dir=output_dir)
    page = blueprint_to_context(pick_relevant_slice(bp, ask=ask))
    waiting = plan_mod.peek(output_dir) if plan_mod.is_agreed(output_dir) else []
    if waiting:
        page = ("STEPS OF AN AGREED PLAN STILL WAITING (each is a later turn, done when they say "
                "`next`; do not do them now, and do not put them in a plan you propose for this "
                "message — they are already planned):\n" + "\n".join(f"- {s}" for s in waiting)
                + "\n\n" + page)
    return page


def template_page(staged: dict, brief: str = "") -> str:
    """What the loop sees for a project started from a template, before it is used.

    The person picked a template in the gallery; the one thing that must be
    settled before anything is defined is whether they want THAT application
    again or something like it. The template's facts are on the page so the
    question, and the answer to "what's in it?", come from what it holds."""
    facts = staged.get("summary") or {}
    counts = facts.get("counts") or {}
    held = ", ".join(f"{counts[k]} {label}" for k, label in (
        ("pages", "screens"), ("entities", "kinds of record"), ("workflows", "processes"),
        ("roles", "roles"), ("requirements", "requirements")) if counts.get(k))
    lines = [
        f"THIS PROJECT WAS STARTED FROM THE TEMPLATE “{staged.get('name')}”, and the template "
        "has not been used yet. Nothing is defined, so the change verbs do not apply.",
        f"What the template is: {(staged.get('description') or facts.get('description') or '')[:500]}",
        f"It holds: {held or 'a definition'}.",
    ]
    for key, label in (("pages", "Screens"), ("entities", "Records"), ("workflows", "Processes"),
                       ("roles", "Roles")):
        if facts.get(key):
            lines.append(f"{label}: " + ", ".join(str(x) for x in facts[key][:16]))
    lines += [
        "",
        "What the person has said so far:",
        brief.strip() or "(nothing yet)",
        "",
        "Settle ONE thing: do they want the exact same app, or something like it but different?",
        "- They have not said → `ask_user` with exactly these options: "
        "\"The exact same app\", \"Something like it, but different\".",
        "- The same app (or the same with small edits like a name, a field or a screen) → "
        "`use_template` with mode \"exact\". Small edits are made after, with the change verbs.",
        "- Something different (another business, other records or processes) → if they have "
        "already said WHAT is different, `use_template` with mode \"adapt\" and `changes` in "
        "their words; if they only said \"something like it\", ask what should be different "
        "(`ask_user`, no options needed).",
        "- A new look as well → `keep_look` false.",
        "Do not call `define_application` or `open_decisions` for this project: the template is "
        "the starting point.",
    ]
    return "\n".join(lines)


__all__ = ["defined", "opening", "template_page"]
