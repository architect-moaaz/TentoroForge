"""§16 — ask before defining, when the brief leaves something material unsaid.

Smith asks well once an application exists: `understand_ask` weighs a change
against the Blueprint and returns a question rather than a guess. Before the
first definition it asked nothing at all. A brief went straight to the DAG
under "Let me define that first", and whatever it had not said was settled by
twenty agents inventing an answer each.

That is the expensive place to guess. A definition run costs a couple of
minutes and every later node builds on it, so a question worth thirty seconds
here saves a rebuild.

ONE QUESTION AT A TIME, IN TURNS. Called on every pre-definition turn against
the brief accumulated so far — which now carries the answers to earlier
questions — and the caller asks only the first question it returns, so each
decision gets a considered answer instead of a wall of them arriving together.
Because the brief grows with each answer, the model asks the NEXT open decision
and returns nothing once they are settled; the caller also caps the rounds, so
a clarifier that could otherwise fire forever always stops and defines. §16
wants Smith to ask rather than to interrogate.

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
that already says enough. They are asked one at a time, so put the single most
important open decision first — and anything the description already answers is
not an open decision.

TWO THINGS ARE WORTH ASKING ABOUT ALMOST WHENEVER THEY ARE UNSAID, because
both are decided once and inherited by every screen:

  LANGUAGE. If the description hints at a language for the INTERFACE — it
  names one, it is written in one, it describes an audience who would expect
  one — ask which language the interface should be in and offer the plausible
  answers. Do not infer it silently: a Cairo hospital may well run in English,
  and a country, currency or market is not a language. Where the description
  settles it outright, do not ask.

  COLOUR. If the description names no colours and points at no existing
  design, propose three palettes the domain actually earns and ask which.
  THEY MUST BE THREE DIFFERENT DIRECTIONS, not three shades of one: one
  warm, one cool, and one that is dark-grounded or otherwise characterful
  (a deep green, an oxblood, a plum) — and never more than one of them a
  slate, navy or charcoal scheme, which is what every app was offered and
  what made every app look the same. Name each one and say what it is for —
  "Ink and oxblood: quiet, papery, for long reading", "Slate and amber:
  dense and operational, for a queue worked all day", "Forest and cream on
  a dark ground: evening, a workshop". Not "blue or green": a choice between
  adjectives is not a choice. The LAST option is always "Let the designer
  choose from the domain" — many people have no preference and should not
  be made to invent one. Where colours are named or a reference is
  attached, do not ask. This question is also where taste is asked, so end
  it by inviting a picture: "…or attach a screenshot of a product whose
  look you like, and it will be designed to that standard." A screenshot
  reaches the designer, the director and the reviewer; an adjective does not.

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


_DESIGN_ATTACHED = """

A DESIGN FILE IS ATTACHED to this brief as its visual specification. Colour,
typography, spacing and layout are settled by it: do not ask about any of
them, and do not propose palettes."""


#: Appended when the ORGANISATION has a design language on record.
#:
#: Not a suppression, unlike `_DESIGN_ATTACHED`. A Figma file attached to this
#: brief has settled the question; a company palette has only made an answer
#: available, and "not every app a company builds should look like the
#: company" is a real position — a public storefront or a white-label tool are
#: the obvious cases. So the question still gets asked, with the company's own
#: palette as the first thing offered.
#:
#: Which is the whole point: the clarifier was asking "which colour palette
#: should this use?" of an organisation that had already told us, during
#: onboarding, exactly what it looks like. Being asked to retype an answer the
#: product already holds is the same failure the discovery exists to prevent.
_COMPANY_PALETTE = """

THIS ORGANISATION HAS A DESIGN LANGUAGE ON RECORD, read from its own website.
If you ask about colour, the FIRST option you offer must be exactly this
string, copied verbatim:

    {option}

Offer one or two alternatives after it for an application that should NOT look
like the rest of the company's things, and keep them concrete in the usual
way. Do not describe the company's palette in your own words and do not
propose a variation on it."""


def company_palette_option(company_name: str, summary: str = "") -> str:
    """The exact option string offered for the company's own design language.

    One definition, used by the prompt that offers it and by the recogniser
    that reads the answer back — two spellings of this would mean a person
    picking the option and nothing happening.
    """
    label = (company_name or "").strip() or "our company"
    detail = f" ({summary.strip()})" if summary.strip() else ""
    return f"Use {label}'s own palette{detail}"


def clarify_brief(
    brief: str,
    *,
    provider: Callable[[str], str] | None = None,
    design_attached: bool = False,
    company_palette: str = "",
) -> list[dict[str, Any]]:
    """`[{question, options}]` — empty when the brief stands on its own.

    `design_attached` says a Figma file travels with the brief. The prompt
    already tells the model not to ask about colour when a reference is
    attached; a bare link in the prose did not read as one, and it asked which
    palette fits a design that had already chosen its own.

    `company_palette` is the option string for the organisation's own design
    language, when it has one (`company_palette_option`). An attached design
    outranks it — that file was attached to THIS application, which is a
    statement about this application specifically — so the two are not
    combined.
    """
    text = (brief or "").strip()
    if not text:
        return []
    if design_attached:
        text = text + _DESIGN_ATTACHED
    elif company_palette.strip():
        text = text + _COMPANY_PALETTE.format(option=company_palette.strip())

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
