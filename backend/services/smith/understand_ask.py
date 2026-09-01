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

  "answer": if they are ASKING ABOUT the application rather than asking you to
      change it — how something works, whether something is stored, what
      happens when they do X — answer it from the Blueprint below, in two or
      three plain sentences, and leave every other field "". Answer only what
      the Blueprint actually says; if it does not say, reply that it does not
      and name what you would need. "" when the request is a change.
  "clarification_needed": a question to ask them, or "" if the request is
      clear enough to act on. Ask when the request names no screen or element,
      when it could plausibly mean two different changes, or when acting on
      the wrong reading would be expensive to undo. Asking is not a failure.
  "verb": WHICH KIND OF CHANGE this is. Exactly one of:
      "rename"        — change the wording of something that already exists.
      "compose_route" — build or rebuild the whole screen at a route. Use this
                        when a route renders nothing, is empty, or 404s, or
                        when they want it laid out again from scratch.
      "add_widgets"   — add named sections to a screen that exists: "put
                        upcoming sessions and quorum status on the dashboard".
      "" when you are asking or answering rather than changing.

Then fill in ONLY the fields that verb needs. Leave the others "".

  rename needs:
  "target_file": the route or schema path the change belongs to. Use a value
      that appears in the Blueprint below — do not invent a path.
  "element_label": the visible text of the thing to change AS IT IS NOW (a
      button's current label, the current heading).
  "new_value": what it should say or become instead, or "" if the request is
      a removal. Give the literal text to write, not a description of it: for
      "call it New plant" the value is "New plant", not "a clearer label".

  compose_route needs:
  "route": the path of the screen, as it appears in the Blueprint ("/",
      "/sessions"). The screen's name works too if that is how they said it.

  add_widgets needs:
  "route": as above, and
  "widgets": a JSON array of the sections to add, each naming WHAT IT SHOWS
      ("Upcoming Sessions", "Quorum Status"). Never an empty array — the
      widgets are the request.

Do not explain. Do not wrap the JSON in prose or code fences.

CHOOSE THE VERB FROM WHAT THEY WANT TO EXIST, NOT FROM HOW MUCH IS THERE. "The
page is empty", "add a dashboard at /", "build the screen at /X" and "put these
five things on the dashboard" are compose_route or add_widgets. Calling one of
them a rename means looking for a label that was never mentioned, finding
nothing, and reporting that the current state already matches — which is
useless to someone whose screen is blank.

A REPLY IS PART OF AN EXCHANGE. When the conversation below ends with a
question of yours, read the request as its answer: "yes" confirms what you
just proposed, and you should act on that proposal rather than ask what it
meant. Do not ask a question the conversation has already answered. If your
question named a route and five widgets and they said "yes please", the verb
is add_widgets and you already know the route and the widgets.

CONVERSATION SO FAR (oldest first, may be empty):
{history}

BLUEPRINT (the relevant part):
{ctx}

REQUEST:
{message}"""


def _default_provider(prompt: str, reasoning: Callable[[str], None] | None = None) -> str:
    from services.llm_client import complete

    return complete(content=prompt, max_tokens=1200,
                    reasoning_callback=reasoning)


def _render_history(history: list | None) -> str:
    """The exchange as plain lines, oldest first.

    Bounded to the last few turns: a clarifying question and its answer are
    adjacent, so the window only has to be long enough to hold the pair, and a
    whole transcript would crowd out the Blueprint slice beside it.
    """
    turns = [t for t in (history or []) if t]
    if not turns:
        return "(nothing yet — this is the first turn)"
    lines = []
    for t in turns[-6:]:
        role, text = (t if isinstance(t, (tuple, list)) and len(t) == 2
                      else ("user", t))
        who = "Smith" if str(role).lower() in ("smith", "assistant") else "They"
        lines.append(f"{who}: {str(text).strip()}")
    return "\n".join(lines)


def understand_ask(
    user_message: str,
    blueprint_ctx: str,
    *,
    history: list | None = None,
    provider: Callable[[str], str] | None = None,
    reasoning: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """(message, ctx) -> {clarification_needed, target_file, element_label, new_value}.

    Never raises. An unreachable or unparseable model becomes a clarification
    request, because the alternative — returning a blank understanding — reads
    downstream as "clear enough to act on, but no target", and `run_iteration`
    would ask a generic question while the real reason went unrecorded.
    """
    ask = (user_message or "").strip()
    if not ask:
        return {"answer": "",
                "clarification_needed": "What would you like to change?",
                "verb": "", "route": "", "widgets": [],
                "target_file": "", "element_label": "", "new_value": ""}

    # SHOWN, NOT JUST HAD. `reasoning` is where Smith's thinking goes on its
    # way to the user; without it the model still reasons and nobody sees it.
    # An INJECTED provider keeps the one-argument seam it has always had —
    # every test supplies a plain `lambda prompt: "..."` and none of them
    # should have to grow a parameter to say it does no thinking.
    call = provider or (lambda prompt: _default_provider(prompt, reasoning))
    try:
        raw = call(_PROMPT.format(ctx=blueprint_ctx or "(nothing yet)",
                                  history=_render_history(history),
                                  message=ask))
    except Exception:  # noqa: BLE001 — a turn degrades, it does not crash
        return {"clarification_needed":
                "I could not reach my reasoning service just then — say that "
                "again and I will try once more.",
                "answer": "", "verb": "", "route": "", "widgets": [],
                "target_file": "", "element_label": "", "new_value": ""}

    data = _parse(raw)
    if data is None:
        return {"clarification_needed":
                "I did not follow that. Which screen should I change, and "
                "what on it?",
                "answer": "", "verb": "", "route": "", "widgets": [],
                "target_file": "", "element_label": "", "new_value": ""}

    # Normalised so `run_iteration`'s `.strip()` checks see strings, not None.
    return {
        # A QUESTION IS NOT AN UNDERSPECIFIED CHANGE. The contract already knew
        # questions arrive here — `new_value` says a question has none — but
        # gave the model nowhere to put one, so the only outcome left was
        # `clarification_needed`. Asked whether the app stores data in a
        # database, Smith replied "could you describe what you'd like to
        # change", with the answer sitting in the Blueprint slice it had been
        # handed. Naming the field is the whole fix; the material was already
        # in the prompt.
        "answer": str(data.get("answer") or "").strip(),
        "clarification_needed": str(data.get("clarification_needed") or "").strip(),
        # WHICH KIND OF CHANGE, asked before which fields. Every request used
        # to be held to a rename's five fields because this prompt only knew
        # how to describe a rename — so "the page at / is empty" came back
        # with an invented element_label, the dispatcher found nothing to
        # rename, and Smith reported that the current state already matched.
        # Six times in one conversation, on a screen that rendered nothing.
        #
        # Empty is still `rename` downstream (`verbs.verb_of`), which is what
        # every caller predating this field already did.
        "verb": str(data.get("verb") or "").strip().lower(),
        "route": str(data.get("route") or "").strip(),
        "widgets": [str(w).strip() for w in (data.get("widgets") or [])
                    if str(w).strip()],
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
