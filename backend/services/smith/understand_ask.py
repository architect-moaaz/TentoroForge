"""§16 — what the user is asking, or what Smith still needs to know.

`run_iteration` has always handled all three outcomes: a clarification
short-circuits the turn to `status="asked"`, a missing `target_file` asks which
screen, and everything else proceeds to the move. The gate was written and had
nothing feeding it — `understand_ask_fn` was never wired, so every iteration
asserted before reaching any of it.

The contract is three fields, and the useful discipline is that ASKING IS A
FIRST-CLASS ANSWER. A model told to always produce a target will always produce
one, including for "make it nicer", and the turn then edits a file nobody
chose. Naming clarification as the preferred outcome when the request is
underspecified is what makes §16's gate real rather than decorative.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

_PROMPT = """You are reading one request from someone changing an application \
they own, against the part of its Blueprint that seems relevant.

Return ONLY a JSON object with exactly these keys:

  "clarification_needed": a question to ask them, or "" if the request is
      clear enough to act on. Ask when the request names no screen or element,
      when it could plausibly mean two different changes, or when acting on
      the wrong reading would be expensive to undo. Asking is not a failure.
  "target_file": the route or schema path the change belongs to, or "" if you
      are asking. Use a value that appears in the Blueprint below — do not
      invent a path.
  "element_label": the visible text of the thing to change AS IT IS NOW (a
      button's current label, the current heading), or "" if you are asking.
  "new_value": what it should say or become instead, or "" if the request is
      not a replacement — a removal, or a question, has no new value. Give the
      literal text to write, not a description of it: for "call it New plant"
      the value is "New plant", not "a clearer label".

Do not explain. Do not wrap the JSON in prose or code fences.

BLUEPRINT (the relevant part):
{ctx}

REQUEST:
{message}"""


def _default_provider(prompt: str) -> str:
    from services.llm_client import complete

    return complete(content=prompt, max_tokens=600)


def understand_ask(
    user_message: str,
    blueprint_ctx: str,
    *,
    provider: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """(message, ctx) -> {clarification_needed, target_file, element_label, new_value}.

    Never raises. An unreachable or unparseable model becomes a clarification
    request, because the alternative — returning a blank understanding — reads
    downstream as "clear enough to act on, but no target", and `run_iteration`
    would ask a generic question while the real reason went unrecorded.
    """
    ask = (user_message or "").strip()
    if not ask:
        return {"clarification_needed": "What would you like to change?",
                "target_file": "", "element_label": "", "new_value": ""}

    call = provider or _default_provider
    try:
        raw = call(_PROMPT.format(ctx=blueprint_ctx or "(nothing yet)",
                                  message=ask))
    except Exception:  # noqa: BLE001 — a turn degrades, it does not crash
        return {"clarification_needed":
                "I could not reach my reasoning service just then — say that "
                "again and I will try once more.",
                "target_file": "", "element_label": "", "new_value": ""}

    data = _parse(raw)
    if data is None:
        return {"clarification_needed":
                "I did not follow that. Which screen should I change, and "
                "what on it?",
                "target_file": "", "element_label": "", "new_value": ""}

    # Normalised so `run_iteration`'s `.strip()` checks see strings, not None.
    return {
        "clarification_needed": str(data.get("clarification_needed") or "").strip(),
        "target_file": str(data.get("target_file") or "").strip(),
        "element_label": str(data.get("element_label") or "").strip(),
        # What to write, not a description of it. `move_dispatcher` needs a
        # literal — "a clearer label" is a note to a person, not an edit — and
        # a removal or a question legitimately has none, so "" is a real value
        # here rather than a missing one.
        "new_value": str(data.get("new_value") or "").strip(),
    }


def _parse(raw: str) -> dict | None:
    """The JSON object in `raw`, however it was wrapped.

    Models fence JSON in ```json blocks and prepend a sentence often enough
    that a bare `json.loads` fails on output that is otherwise perfectly good.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None
