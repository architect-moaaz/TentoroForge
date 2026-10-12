"""The idea board: what the person and Smith have worked out so far.

Sections of items, each item known by its `name`. Smith changes the board
with `update_board`: an item sent is put in place of the one with the same
name (or added), `remove` takes items out by name, and the single-valued
sections (`product`, `look`) are merged field by field. The person sees the
board beside the conversation, and the requirements document is written from
it when they agree.
"""
from __future__ import annotations

import copy
from typing import Any

LISTS = ("references", "roles", "features", "screens", "flows", "entities", "decisions", "questions")
SINGLE = ("product", "look")
PRIORITIES = ("must", "should", "later")


def empty() -> dict:
    return {"product": {}, "look": {}, **{k: [] for k in LISTS}, "status": "exploring"}


def _key(item: Any) -> str:
    if isinstance(item, dict):
        return " ".join(str(item.get("name") or item.get("text") or "").lower().split())
    return " ".join(str(item).lower().split())


def apply(board: dict, change: dict) -> tuple[dict, list[str]]:
    """The board with `change` applied, and what in it did not fit (said back
    to Smith, never refused: a board is a draft)."""
    out = copy.deepcopy(board) if board else empty()
    notes: list[str] = []
    for k in SINGLE:
        part = change.get(k)
        if isinstance(part, dict):
            out.setdefault(k, {})
            out[k].update({f: v for f, v in part.items() if v not in (None, "")})
    for k in LISTS:
        rows = out.setdefault(k, [])
        for name in change.get("remove", {}).get(k, []) if isinstance(change.get("remove"), dict) else []:
            before = len(rows)
            rows[:] = [r for r in rows if _key(r) != _key(name)]
            if len(rows) == before:
                notes.append(f"{k}: nothing called {name!r} to remove")
        for item in change.get(k) or []:
            if isinstance(item, str):
                item = {"text": item} if k in ("decisions", "questions") else {"name": item}
            if not isinstance(item, dict) or not _key(item):
                notes.append(f"{k}: an item with no name was left out")
                continue
            if k == "features" and item.get("priority") not in (None, *PRIORITIES):
                notes.append(f"features: {item.get('name')!r} priority {item.get('priority')!r} is not one of "
                             f"{', '.join(PRIORITIES)}; kept as 'should'")
                item["priority"] = "should"
            at = next((i for i, r in enumerate(rows) if _key(r) == _key(item)), None)
            if at is None:
                rows.append(item)
            else:
                rows[at] = {**rows[at], **item}
    if change.get("status") in ("exploring", "agreed"):
        out["status"] = change["status"]
    notes += findings(out)
    return out, notes


def findings(board: dict) -> list[str]:
    """What on the board names what is not on it: a flow through a screen
    there is no screen for, a record linked to a record that is not there."""
    out: list[str] = []
    screens = {_key(s) for s in board.get("screens") or []}
    roles = {_key(r) for r in board.get("roles") or []}
    for f in board.get("flows") or []:
        for st in f.get("steps") or []:
            if isinstance(st, dict) and st.get("screen") and _key(st["screen"]) not in screens:
                out.append(f"flow {f.get('name')!r} goes through {st['screen']!r}, which is not a screen on the board")
        if f.get("role") and roles and _key(f["role"]) not in roles:
            out.append(f"flow {f.get('name')!r} is taken by {f['role']!r}, who is not a role on the board")
    ents = {_key(e) for e in board.get("entities") or []}
    for e in board.get("entities") or []:
        for link in e.get("links") or []:
            if isinstance(link, dict) and link.get("to") and _key(link["to"]) not in ents:
                out.append(f"record {e.get('name')!r} links to {link['to']!r}, which is not a record on the board")
    return out


def summary(board: dict) -> str:
    """The board in a few lines, for the start of each of Smith's turns."""
    b = board or {}
    p = b.get("product") or {}
    parts = [f"status: {b.get('status') or 'exploring'}"]
    if p.get("name") or p.get("pitch"):
        parts.append(f"product: {p.get('name') or '(unnamed)'} — {p.get('pitch') or ''}".strip(" —"))
    for k in LISTS:
        rows = b.get(k) or []
        if rows:
            parts.append(f"{k} ({len(rows)}): " + "; ".join(_key(r) for r in rows[:30]))
    if b.get("look"):
        parts.append("look: " + ", ".join(f"{k}" for k in b["look"]))
    return "\n".join(parts)


#: The board's shape, as the `update_board` tool declares it.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "product": {"type": "object", "description": "What the app is.",
                    "properties": {"name": {"type": "string"}, "pitch": {"type": "string"},
                                   "audience": {"type": "string"},
                                   "platforms": {"type": "array", "items": {"type": "string"}},
                                   "kind": {"type": "string"}}},
        "references": {"type": "array", "description": "Apps or sites studied, and what is taken from each.",
                       "items": {"type": "object", "properties": {
                           "name": {"type": "string"}, "url": {"type": "string"}, "why": {"type": "string"},
                           "took": {"type": "array", "items": {"type": "string"}}}, "required": ["name"]}},
        "roles": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "does": {"type": "string"}}, "required": ["name"]}},
        "features": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "detail": {"type": "string"},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "from": {"type": "string", "description": "the reference it comes from, or 'you' for the person"}},
            "required": ["name"]}},
        "screens": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "role": {"type": "string"}, "purpose": {"type": "string"},
            "shows": {"type": "array", "items": {"type": "string"}},
            "actions": {"type": "array", "items": {"type": "string"}},
            "like": {"type": "string", "description": "id of a screenshot it is modelled on"}},
            "required": ["name"]}},
        "flows": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "role": {"type": "string"}, "goal": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "object", "properties": {
                "screen": {"type": "string"}, "does": {"type": "string"}}, "required": ["screen"]}}},
            "required": ["name", "steps"]}},
        "entities": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "fields": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "type": {"type": "string"}}, "required": ["name"]}},
            "links": {"type": "array", "items": {"type": "object", "properties": {
                "to": {"type": "string"}, "kind": {"type": "string", "enum": ["one", "many"]}},
                "required": ["to"]}}},
            "required": ["name"]}},
        "look": {"type": "object", "properties": {
            "mood": {"type": "string"},
            "palette": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "hex": {"type": "string"}}}},
            "fonts": {"type": "array", "items": {"type": "string"}},
            "layout": {"type": "string"}, "avoid": {"type": "string"}}},
        "decisions": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}},
        "questions": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}}},
            "required": ["text"]}},
        "remove": {"type": "object", "description": "Names to take out, by section.",
                   "properties": {k: {"type": "array", "items": {"type": "string"}} for k in LISTS}},
        "status": {"type": "string", "enum": ["exploring", "agreed"]},
    },
}

__all__ = ["empty", "apply", "findings", "summary", "SCHEMA", "LISTS", "SINGLE", "PRIORITIES"]
