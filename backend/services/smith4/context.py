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


def opening(project_id: str, output_dir: str, ask: str) -> str:
    """The Blueprint slice for `ask`, with the turn-to-turn state on top."""
    bp = Blueprint.load(project_id=project_id, output_dir=output_dir)
    page = blueprint_to_context(pick_relevant_slice(bp, ask=ask))
    waiting = plan_mod.peek(output_dir)
    if waiting:
        page = ("STEPS OF AN AGREED PLAN STILL WAITING (each is a later turn; do "
                "not do them now):\n" + "\n".join(f"- {s}" for s in waiting)
                + "\n\n" + page)
    return page


__all__ = ["opening"]
