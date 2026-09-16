"""Several asks in one message, done one at a time instead of one of them.

"Add a phone number, show it on the form, and make it required" is three
changes. `understand_ask` returns ONE verb, so the other two were dropped
silently — the biggest one happened and the person found out later that the
rest had not.

The model reads the whole message, so it is the thing that can split it: it
returns the other asks as sentences in the user's own words. This keeps them
between turns, the way `pending_ask` keeps an unanswered ask, so the steps can
be shown as a plan, agreed to once, and then worked through — each one a
normal turn, able to ask its own questions, with the rest still waiting.

Nothing is done before the plan is agreed. The alternative — starting on step
one while showing the list — is the silent behaviour with a receipt.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PENDING_PATH = Path(".forge") / "pending-plan.json"

#: How many steps one yes can cover. More than this on screen is a list nobody
#: reads before agreeing to it — but the ones past it are SAID rather than
#: dropped: silently keeping six of nine is the same silence this module
#: exists to end, at a different number.
MAX_STEPS = 6

#: What the chips say when the plan is offered.
ALL_LABEL = "Do them in order"
FIRST_LABEL = "Just the first one"
REWORD_LABEL = "Let me say it differently"

#: Carrying on to the next step, as a whole message.
_NEXT = frozenset({"next", "next one", "go on", "carry on", "continue",
                   "keep going", "and the next", "do the next one", "yes"})


def _path(output_dir: str | Path) -> Path:
    return Path(output_dir) / PENDING_PATH


def split(steps: list[str]) -> tuple[list[str], list[str]]:
    """The steps one yes can cover, and the ones past that — which are named
    in the question rather than dropped out of it."""
    tidy = [" ".join(str(s).split()) for s in (steps or []) if str(s or "").strip()]
    return tidy[:MAX_STEPS], tidy[MAX_STEPS:]


def remember(output_dir: str | Path, steps: list[str]) -> None:
    """Keep the steps still to do, in order."""
    kept, _over = split(steps)
    if not kept:
        clear(output_dir)
        return
    try:
        path = _path(output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"steps": kept}, indent=2), "utf-8")
    except Exception as exc:  # noqa: BLE001 — a plan that cannot be kept is asked again
        logger.warning("[smith] could not record the plan: %s", exc)


def peek(output_dir: str | Path) -> list[str]:
    """The steps still waiting, without consuming them."""
    try:
        raw = json.loads(_path(output_dir).read_text("utf-8"))
        return [str(s) for s in (raw or {}).get("steps") or []] if isinstance(raw, dict) else []
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[smith] plan unreadable: %s", exc)
        return []


def take_next(output_dir: str | Path) -> str:
    """The next step, removed from the plan. "" when the plan is empty."""
    steps = peek(output_dir)
    if not steps:
        return ""
    first, rest = steps[0], steps[1:]
    remember(output_dir, rest) if rest else clear(output_dir)
    return first


def clear(output_dir: str | Path) -> None:
    try:
        _path(output_dir).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[smith] could not clear the plan: %s", exc)


def wants_next(message: str) -> bool:
    """Whether a message is "carry on with the plan"."""
    m = " ".join((message or "").strip().lower().rstrip(".!").split())
    return m in _NEXT


def as_question(steps: list[str], overflow: list[str] | None = None) -> str:
    """The plan, numbered, with the question under it — and anything that did
    not fit, said out loud."""
    planned, over = (steps, list(overflow or [])) if overflow is not None else split(steps)
    lines = ["That is more than one change. Here is what I would do, in order:"]
    lines += [f"{i}. {s}" for i, s in enumerate(planned, start=1)]
    if over:
        lines += ["",
                  f"You asked for {len(over)} more than I can plan in one go — "
                  "tell me these again once the list above is done:"]
        lines += [f"- {s}" for s in over]
    lines += ["", "Shall I work through them?"]
    return "\n".join(lines)


def remaining_note(steps: list[str]) -> str:
    """What to add to a step's reply so the rest is not forgotten."""
    if not steps:
        return ""
    if len(steps) == 1:
        return f"\n\nStill to do: **{steps[0]}**. Say `next` and I will."
    listed = "\n".join(f"- {s}" for s in steps)
    return f"\n\nStill to do:\n{listed}\n\nSay `next` for the first of them."


__all__ = ["ALL_LABEL", "FIRST_LABEL", "REWORD_LABEL", "MAX_STEPS", "PENDING_PATH",
           "as_question", "clear", "peek", "remaining_note", "remember", "split",
           "take_next", "wants_next"]
