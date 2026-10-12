"""The Researcher's dossier: what a reference app is, as found, with sources.

Like the idea board, sections of items known by `name` (`text` for rules,
voices and gaps): an item recorded again with the same name is merged into
the one already there, so workers studying different surfaces of the same
app add to one dossier rather than writing over each other. Unlike the
board, it is a record of what IS — the reference — never of what the new
app will be; Smith and the person decide that from it.
"""
from __future__ import annotations

import copy
from typing import Any

from services.brain_juice.board import _key

LISTS = ("surfaces", "roles", "features", "screens", "flows", "entities", "rules", "voices", "gaps")
SINGLE = ("product", "look")


def empty() -> dict:
    return {"product": {}, "look": {}, **{k: [] for k in LISTS}}


def merge(dossier: dict, change: dict) -> tuple[dict, list[str]]:
    """`dossier` with `change` recorded, and what in it was left out."""
    out = copy.deepcopy(dossier) if dossier else empty()
    notes: list[str] = []
    for k in SINGLE:
        part = change.get(k)
        if isinstance(part, dict):
            out.setdefault(k, {})
            for f, v in part.items():
                if v in (None, "", [], {}):
                    continue
                if isinstance(v, list) and isinstance(out[k].get(f), list):
                    seen = {_key(x) for x in out[k][f]}
                    out[k][f] = out[k][f] + [x for x in v if _key(x) not in seen]
                else:
                    out[k][f] = v
    for k in LISTS:
        rows = out.setdefault(k, [])
        for item in change.get(k) or []:
            if isinstance(item, str):
                item = {"text": item} if k in ("rules", "voices", "gaps") else {"name": item}
            if not isinstance(item, dict) or not _key(item):
                notes.append(f"{k}: an item with no name was left out")
                continue
            at = next((i for i, r in enumerate(rows) if _key(r) == _key(item)), None)
            if at is None:
                rows.append(item)
                continue
            merged = {**rows[at]}
            for f, v in item.items():
                if v in (None, "", []) or f in ("name", "text"):
                    continue                  # the first spelling of a name stands
                if isinstance(v, list) and isinstance(merged.get(f), list) and f != "steps":
                    seen = {_key(x) for x in merged[f]}
                    merged[f] = merged[f] + [x for x in v if _key(x) not in seen]
                else:
                    merged[f] = v
            rows[at] = merged
    return out, notes


def counts(dossier: dict) -> dict[str, int]:
    return {k: len(dossier.get(k) or []) for k in LISTS}


def brief(dossier: dict, limit: int = 60000) -> str:
    """The dossier as text for a model to read, largest sections last."""
    import json
    order = ("product", "surfaces", "roles", "look", "features", "screens", "flows", "entities", "rules",
             "voices", "gaps")
    text = json.dumps({k: dossier.get(k) for k in order if dossier.get(k)}, indent=1, default=str)
    return text if len(text) <= limit else text[:limit] + "\n… (cut short)"


_ITEMS = lambda props, required=("name",): {  # noqa: E731 — a schema helper
    "type": "array", "items": {"type": "object", "properties": props, "required": list(required)}}
_STR = {"type": "string"}
_STRS = {"type": "array", "items": {"type": "string"}}

#: What `record` accepts — every section optional, as much or as little as was found.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "product": {"type": "object", "properties": {
            "name": _STR, "what": _STR, "audience": _STR, "platforms": _STRS, "business": _STR}},
        "surfaces": _ITEMS({"name": _STR, "url": _STR,
                            "kind": {"type": "string", "enum": ["website", "ios", "android", "help", "seller",
                                                                "partner", "admin", "other"]},
                            "reachable": {"type": "boolean"}, "note": _STR}),
        "roles": _ITEMS({"name": _STR, "does": _STR}),
        "features": _ITEMS({"name": _STR, "detail": _STR, "area": _STR, "where": _STR,
                            "source": {"type": "string", "description": "the URL it was seen at"}}),
        "screens": _ITEMS({"name": _STR, "surface": _STR, "url": _STR, "purpose": _STR, "shows": _STRS,
                           "actions": _STRS,
                           "shot": {"type": "string", "description": "id of the screenshot of it"}}),
        "flows": _ITEMS({"name": _STR, "role": _STR, "goal": _STR,
                         "steps": {"type": "array", "items": {"type": "object", "properties": {
                             "screen": _STR, "does": _STR}, "required": ["screen"]}}},
                        ("name", "steps")),
        "entities": _ITEMS({"name": _STR,
                            "fields": {"type": "array", "items": {"type": "object", "properties": {
                                "name": _STR, "type": _STR}, "required": ["name"]}},
                            "links": {"type": "array", "items": {"type": "object", "properties": {
                                "to": _STR, "kind": {"type": "string", "enum": ["one", "many"]}},
                                "required": ["to"]}}}),
        "rules": _ITEMS({"text": _STR, "source": _STR}, ("text",)),
        "voices": _ITEMS({"text": _STR, "kind": {"type": "string", "enum": ["love", "hate", "wish"]},
                          "source": _STR}, ("text",)),
        "look": {"type": "object", "properties": {
            "mood": _STR, "palette": {"type": "array", "items": {"type": "object", "properties": {
                "name": _STR, "hex": _STR}}},
            "fonts": _STRS, "layout": _STR, "density": _STR, "signature": _STRS}},
        "gaps": _ITEMS({"text": _STR}, ("text",)),
    },
}

__all__ = ["empty", "merge", "counts", "brief", "SCHEMA", "LISTS", "SINGLE"]
