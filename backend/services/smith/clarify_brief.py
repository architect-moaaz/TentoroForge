"""§16 — ask before defining, when the brief leaves something material unsaid.

Smith asks well once an application exists: `understand_ask` weighs a change
against the Blueprint and returns a question rather than a guess. Before the
first definition it asked nothing at all. A brief went straight to the DAG
under "Let me define that first", and whatever it had not said was settled by
twenty agents inventing an answer each.

That is the expensive place to guess. A definition run costs a couple of
minutes and every later node builds on it, so a question worth thirty seconds
here saves a rebuild.

ONE ROUND, AND ONLY AT THE START. Asked only when the conversation has no
history — the first thing anybody says. Once they have answered, or said
anything at all, the next message defines. A clarifier that can fire twice is
a clarifier that can fire forever, and §16 wants Smith to ask rather than to
interrogate.

SILENCE IS THE DEFAULT. A brief that names what the application is for and
what people do in it needs no question, and asking anyway is worse than not
asking: it reads as not having listened. Every failure — no provider, bad
JSON, an empty answer — resolves to no question and the definition proceeds.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

_PROMPT = """Someone has described an application they want built. It will now
be defined in detail by a team of agents, and anything the description leaves
unsaid will be decided for them.

Ask about what would change what gets built, and about nothing else. At most
three questions; fewer is better and none is a good answer for a description
that already says enough.

TWO THINGS ARE WORTH ASKING ABOUT ALMOST WHENEVER THEY ARE UNSAID, because
both are decided once and inherited by every screen:

  LANGUAGE. If the description hints at a language for the INTERFACE — it
  names one, it is written in one, it describes an audience who would expect
  one — ask which language the interface should be in and offer the plausible
  answers. Do not infer it silently: a Cairo hospital may well run in English,
  and a country, currency or market is not a language. Where the description
  settles it outright, do not ask.

  COLOUR. If the description names no colours and points at no existing
  design, propose two or three palettes the domain actually earns and ask
  which. Name each one and say what it is for — "Ink and oxblood: quiet,
  papery, for long reading", "Slate and amber: dense and operational, for a
  queue worked all day". Not "blue or green": a choice between adjectives is
  not a choice. Where colours are named or a reference is attached, do not
  ask.

Otherwise ask only what a definition cannot proceed honestly without: who uses
this and whether they differ, whether records are shared or private, what
happens after the last step described. Not anything you can reasonably decide,
not anything already said, and nothing so broad it asks them to write the
brief again.

Return ONLY a JSON object:

  "questions": a list, at most three, each
      {{"question": "...", "options": ["...", "..."]}}.
      Options are 2-4 short concrete answers they could pick; [] only when the
      question is genuinely open. Offering answers is how a question stops
      being homework.
      An empty list asks nothing, which is the right answer more often than
      not.

Do not explain. Do not wrap the JSON in prose or code fences.

WHAT THEY WROTE:
{brief}"""


def _default_provider(prompt: str) -> str:
    from services.llm_client import complete

    return complete(content=prompt, max_tokens=400)


def clarify_brief(
    brief: str,
    *,
    provider: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """`[{question, options}]` — empty when the brief stands on its own."""
    text = (brief or "").strip()
    if not text:
        return []

    # BUILT BEFORE THE TRY. `str.format` on a prompt containing literal JSON
    # braces raises KeyError, and inside the guard below that is indis-
    # tinguishable from a provider that declined to answer — the clarifier
    # simply stopped asking anything and looked like it had decided not to.
    # A broken template is a bug here, not a degraded turn out there.
    prompt = _PROMPT.format(brief=text)

    call = provider or _default_provider
    try:
        raw = call(prompt)
    except Exception:  # noqa: BLE001 — a question is a courtesy, never a gate
        return []

    data = _parse(raw)
    if not isinstance(data, dict):
        return []

    out: list[dict[str, Any]] = []
    for item in (data.get("questions") or [])[:3]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        options = [str(o).strip() for o in (item.get("options") or [])
                   if str(o).strip()]
        out.append({"question": question, "options": options[:4]})
    return out


def _parse(raw: str) -> dict | None:
    """The JSON object in `raw`, however it was wrapped."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:  # noqa: BLE001
        return None
