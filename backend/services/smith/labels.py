"""Finding the control a person named, instead of making them spell it.

`rename` and `remove` matched the label by string equality, so "remove the
delete thing" and "remove the Delete  button" both reached "I looked for it
and could not find it" while a control called `Delete` sat in the tree. That
is string matching delegated to the user — and the tree that knows the answer
is right there.

A HEURISTIC THAT ASKS, NOT ONE THAT GUESSES. Matching is widened in steps and
each step is narrower than the last is wide: exact, then ignoring case and
punctuation, then one label containing the other. The moment more than one
control answers, nothing is chosen — the candidates are handed back for the
caller to ask about, with where each one lives, because "Delete" on the list
and "Delete" on the record are different buttons and picking one is a coin
toss with somebody's application.
"""

from __future__ import annotations

import re
from typing import Any

#: The props a person reads as the name of a control. Same list the move edits,
#: so anything findable here is something it can act on.
from services.smith.move_dispatcher import _TEXT_PROPS

#: What kind of thing a label sits on, in a person's words. The prop it was
#: found under is the truth; this is how that reads back in a question.
KIND_BY_PROP = {"label": "button", "content": "text", "title": "heading",
                "text": "text", "heading": "heading", "placeholder": "hint"}

#: A control that lives INSIDE a prop is named by the prop that holds it — a
#: `fields` entry is a box to type in and a `rowActions` entry is a link on
#: every row, and calling both "the button" makes the question useless.
KIND_BY_CONTAINER = {"fields": "field", "columns": "column",
                     "rowActions": "row action", "actions": "action",
                     "items": "item", "options": "option", "tabs": "tab",
                     "steps": "step", "links": "link"}

_PUNCT = re.compile(r"[^a-z0-9]+")

#: A node names its own kind better than the prop does: a Heading carries its
#: words in `content`, which would otherwise read back as "the text".
_KIND_BY_TYPE = {"Heading": "heading", "Button": "button", "Link": "link",
                 "Badge": "badge", "Tag": "badge", "Stat": "figure",
                 "Text": "text", "Card": "card", "Section": "section"}


def _kind_of_node(node: Any) -> str:
    return _KIND_BY_TYPE.get(str((node or {}).get("type") or ""), "")


def normalise(text: str) -> str:
    """Lowercase, letters and digits only — "Add Nurse", "add  nurse" and
    "Add-Nurse!" are the same words to a reader, and were three strings."""
    return _PUNCT.sub(" ", str(text or "").lower()).strip()


def _walk(node: Any, container: str = ""):
    """Every dict in the tree, with the prop that holds it — "" for a node of
    the tree itself, `fields` or `rowActions` for a control inside a prop."""
    if isinstance(node, list):
        for item in node:
            yield from _walk(item, container)
        return
    if not isinstance(node, dict):
        return
    yield node, container
    for child in node.get("children") or []:
        yield from _walk(child, "")
    for key, value in (node.get("props") or {}).items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item, key


def collect(doc: dict) -> list[dict]:
    """Every visible label in the application, with where it lives.

    One entry per (text, kind, page): the same words on two screens are two
    answers to "which one?", and the same words twice on one screen are one.
    """
    pages = {str(p.get("id")): p for p in (doc or {}).get("pages") or []
             if isinstance(p, dict)}
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for layout in (doc or {}).get("pageLayouts") or []:
        if not isinstance(layout, dict) or layout.get("status") in ("SUPERSEDED", "DEPRECATED"):
            continue
        page = pages.get(str(layout.get("page"))) or {}
        route = str(page.get("route") or "")
        name = str(page.get("name") or route)
        for node, container in _walk(layout.get("root")):
            props = node.get("props") if isinstance(node.get("props"), dict) else node
            if not isinstance(props, dict):
                continue
            for prop in _TEXT_PROPS:
                text = props.get(prop)
                if not isinstance(text, str) or not text.strip():
                    continue
                kind = (KIND_BY_CONTAINER.get(container)
                        or _kind_of_node(node)
                        or KIND_BY_PROP.get(prop, prop))
                key = (text.strip(), kind, route)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"text": text.strip(), "kind": kind, "route": route,
                            "page": name, "prop": prop})
    return out


def describe(entry: dict) -> str:
    """One candidate, as the question offers it."""
    where = entry.get("page") or entry.get("route") or ""
    return f"“{entry['text']}” — the {entry['kind']} on {where}".strip()


def resolve(doc: dict, asked: str, route: str = "") -> dict:
    """What `asked` names: `{"text": …}` when one control answers, or
    `{"candidates": [...]}` when several do, or neither when none do.

    `route` narrows first, so "remove the delete button on Master Data" never
    has to disambiguate at all.
    """
    want = normalise(asked)
    if not want:
        return {}
    entries = collect(doc)
    if route:
        scoped = [e for e in entries if normalise(e["route"]) == normalise(route)
                  or normalise(e["page"]) == normalise(route)]
        entries = scoped or entries

    def _unique(rows: list[dict]) -> dict:
        """One answer, or the choices.

        Grouped by SCREEN, not by exact text: the same words twice on one page
        — a button in a header and the same button in an empty state — are one
        control to a person and the move edits both deliberately. The same
        words on two screens are two controls, and picking one is a coin toss
        with somebody's application.
        """
        if len({r["route"] for r in rows}) == 1 and len({r["text"] for r in rows}) == 1:
            return {"text": rows[0]["text"], "matched": rows}
        return {"candidates": rows}

    exact = [e for e in entries if e["text"].strip() == asked.strip()]
    if exact:
        return _unique(exact)
    same = [e for e in entries if normalise(e["text"]) == want]
    if same:
        return _unique(same)
    # One contains the other: "the delete button" finds "Delete", and "Delete"
    # finds "Delete nurse". Bounded to words, so "a" does not match everything.
    if len(want) >= 3:
        near = [e for e in entries
                if want in normalise(e["text"]) or normalise(e["text"]) in want]
        if near:
            return _unique(near)
    return {}


__all__ = ["collect", "describe", "normalise", "resolve", "KIND_BY_PROP"]
