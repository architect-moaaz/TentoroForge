"""The answers a question already has, so no question is homework.

A missing fact was reported in the contract's own words — "I can do that, I
just need entity and field" — which names an internal slot and leaves the
person to supply a value they have to know Smith's spelling of. For most of
these slots the answer set is FINITE AND WRITTEN DOWN: the entities, the
screens, the workflows and the rules are all in the Blueprint. Asking with
them attached turns a dead end into a click.

Only where the answer is genuinely open — new wording, a link, a description
of a change — is the question left as a question. An empty option list is not
a failure here; it is the honest shape of "what should it say instead?".
"""

from __future__ import annotations

from typing import Any

#: slot -> how to ask for it in the words a person uses. `entity` is a record,
#: `route` is a screen; the contract's nouns never reach the reply (§7).
ASKS: dict[str, str] = {
    "entity": "Which record?",
    "field": "Which box on that record?",
    "route": "Which screen?",
    "target_file": "Which screen?",
    "workflow": "Which automatic process?",
    "rule": "Which rule?",
    "requirement": "Which requirement?",
    "api": "Which endpoint?",
    "integration": "Which outside service?",
    "change": "What should be different about it?",
    # An account is identified by the address its person signs in with, so the
    # question asks for that and says why — "which person?" invites "Dave",
    # which is the request again rather than an answer to it.
    "email": "What email address will they sign in with?",
    "person": "Which person? Their email address, or the name their login was set up under.",
    "new_value": "What should it say instead?",
    "element_label": "Which control? Copy the words printed on it.",
    "widgets": "What should go on it?",
    "screen": "Which screen?",
    "current_behavior": "What does it do now?",
    "desired_behavior": "What should it do instead?",
    "figma_url": "Paste the Figma link.",
    "uxpilot_ref": "Paste the UX Pilot page or its id.",
    "token_env": "Which environment variable holds the token? The NAME, never the token.",
    "key_env": "Which environment variable holds the key? The NAME, never the key.",
}

#: How many choices a question may carry. Past this it is a directory, not a
#: question, and the chips push the question itself off the screen.
MAX_OPTIONS = 5


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict)
            and r.get("status") not in ("DEPRECATED", "SUPERSEDED")]


def _entities(doc: dict) -> list[dict]:
    return _live(((doc or {}).get("data") or {}).get("entities"))


def options_for(slot: str, doc: dict, understanding: dict | None = None) -> list[str]:
    """Every answer to `slot` this application actually has, in document order.

    `understanding` narrows where one slot depends on another: the boxes worth
    offering are the ones on the record they already named.
    """
    doc = doc or {}
    said = understanding or {}

    if slot == "entity":
        return [str(e.get("name")) for e in _entities(doc) if e.get("name")][:MAX_OPTIONS]

    if slot == "field":
        want = str(said.get("entity") or "").strip().lower()
        ents = _entities(doc)
        ent = next((e for e in ents if str(e.get("name") or "").lower() == want), None)
        if ent is None:
            return []                      # no record named yet: ask for that first
        managed = {"id", "createdat", "updatedat"}
        return [str(f.get("name")) for f in (ent.get("fields") or [])
                if isinstance(f, dict) and f.get("name")
                and str(f["name"]).lower() not in managed and not f.get("primaryKey")][:MAX_OPTIONS]

    if slot in ("route", "target_file", "screen"):
        return [str(p.get("route")) for p in _live(doc.get("pages")) if p.get("route")][:MAX_OPTIONS]

    if slot == "workflow":
        return [str(w.get("name")) for w in _live(doc.get("workflows")) if w.get("name")][:MAX_OPTIONS]

    if slot == "rule":
        return [str(r.get("name")) for r in _live(doc.get("businessRules")) if r.get("name")][:MAX_OPTIONS]

    if slot == "requirement":
        out = []
        for r in _live(doc.get("requirements")):
            desc = " ".join(str(r.get("description") or "").split())
            if r.get("id"):
                out.append(f"{r['id']} — {desc[:60]}" if desc else str(r["id"]))
        return out[:MAX_OPTIONS]

    if slot == "api":
        return [f"{a.get('method')} {a.get('path')}" for a in _live(doc.get("apis"))
                if a.get("path")][:MAX_OPTIONS]

    if slot == "integration":
        return [str(i.get("name")) for i in _live(doc.get("integrations")) if i.get("name")][:MAX_OPTIONS]

    return []                              # open question: a value, not a choice


def fill_from(gaps: list[str], message: str, doc: dict,
              understanding: dict | None = None) -> dict:
    """The gaps whose answer is already in what they said.

    "Delete the Master Data page" names the screen; asking which screen is
    asking a person to repeat themselves. Only an UNAMBIGUOUS match counts —
    exactly one of the known answers appears in the message — because two
    matches is a real question and picking one is a guess.
    """
    from services.smith.labels import normalise

    said = normalise(message)
    if not said:
        return {}
    found: dict[str, str] = {}
    for gap in gaps:
        hits = [o for o in options_for(gap, doc, understanding)
                if normalise(o) and normalise(o) in said]
        # A route is also named by its page's title ("the Master Data page"),
        # which is not the option text — so the pages are matched by name too.
        if not hits and gap in ("route", "target_file", "screen"):
            for page in _live(doc.get("pages")):
                name = normalise(str(page.get("name") or ""))
                if name and name in said and page.get("route"):
                    hits.append(str(page["route"]))
        if len(set(hits)) == 1:
            found[gap] = hits[0]
    return found


def ask_for(gaps: list[str], doc: dict, understanding: dict | None = None) -> tuple[str, list[str]]:
    """The question to ask for the first missing fact, and its choices.

    ONE AT A TIME, and the one that can be answered with a click first: a
    question carrying its own answers moves faster than two open ones, and the
    rest of the gaps are asked for on the turns after it.
    """
    ordered = sorted(gaps, key=lambda g: 0 if options_for(g, doc, understanding) else 1)
    for gap in ordered:
        options = options_for(gap, doc, understanding)
        if options:
            return ASKS.get(gap, f"Which {gap}?"), options
    first = ordered[0] if ordered else ""
    return ASKS.get(first, f"I need {first}." if first else "I need one more detail."), []


__all__ = ["ASKS", "MAX_OPTIONS", "options_for", "ask_for"]
