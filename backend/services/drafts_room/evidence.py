"""Evidence: what a study found, each fact with its standing.

A deep study records what a reference product IS as facts that each say
how well they are known: `observed` (seen directly — a field in a response,
a control on a screen), `derived` (computed from observed facts: a flow from
the order pages were visited), `inferred` (a reasoned guess, said so) or
`unknown` (looked for and not found). Every item names its source. The
standing is the whole point: a card written from evidence says what was
seen and what was guessed, and a draft built from cards keeps that honest.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from services.drafts_room.board import _key

STANDINGS = ("observed", "derived", "inferred", "unknown")
KINDS = ("record", "field", "enum", "action", "screen", "flow", "rule", "role", "voice", "gap")
#: Sources that are a captured fact: only these can raise an item's standing.
CAPTURED = ("response", "request", "page", "har", "screenshot")


def item(reference: str, kind: str, text: str, *, standing: str, source: dict, data: Any = None) -> dict:
    if standing not in STANDINGS:
        raise ValueError(f"{standing!r} is not a standing")
    if kind not in KINDS:
        raise ValueError(f"{kind!r} is not a kind of evidence")
    return {"id": uuid.uuid4().hex[:10], "reference": reference, "kind": kind,
            "text": " ".join(str(text or "").split())[:300], "data": data, "standing": standing,
            "sources": [dict(source)], "at": time.time()}


def _rank(standing: str) -> int:
    return STANDINGS.index(standing) if standing in STANDINGS else len(STANDINGS)


def merge(items: list[dict], new: list[dict]) -> tuple[list[dict], list[str]]:
    """`items` with `new` recorded. Identity is the reference, the kind and
    the text. A standing is RAISED only by a captured source and NEVER
    lowered: what was seen stays seen whatever a later guess says, and a
    guess cannot promote itself. Sources accumulate; `data` is taken from
    the better-standing item."""
    out = [dict(i) for i in items]
    by_key = {(i["reference"], i["kind"], _key(i["text"])): n for n, i in enumerate(out)}
    notes: list[str] = []
    for n_item in new:
        key = (n_item["reference"], n_item["kind"], _key(n_item["text"]))
        at = by_key.get(key)
        if at is None:
            out.append(dict(n_item))
            by_key[key] = len(out) - 1
            continue
        held = out[at]
        new_sources = [s for s in n_item.get("sources") or [] if s not in (held.get("sources") or [])]
        held["sources"] = (held.get("sources") or []) + new_sources
        captured = any(s.get("type") in CAPTURED for s in n_item.get("sources") or [])
        if _rank(n_item["standing"]) < _rank(held["standing"]):
            if captured:
                held["standing"] = n_item["standing"]
                held["data"] = n_item.get("data") if n_item.get("data") is not None else held.get("data")
            else:
                notes.append(f"{held['kind']} {held['text']!r} stays {held['standing']}: a {n_item['standing']} "
                             "claim without a captured source does not raise it")
        elif held.get("data") is None and n_item.get("data") is not None:
            held["data"] = n_item["data"]
    return out, notes


def from_dossier(job: dict) -> list[dict]:
    """The surface study's dossier as evidence: what the Researcher saw on a
    page it can point at is observed; what it wrote without a page is
    inferred; its gaps are unknown."""
    ref = str(job.get("reference_id") or job.get("reference") or "")
    d = job.get("dossier") or {}
    out: list[dict] = []

    def src(url: str | None, kind: str = "page") -> dict:
        return {"type": kind if url else "dossier", "ref": job.get("id"), "url": url or ""}

    for s in d.get("screens") or []:
        url = s.get("url") or ""
        out.append(item(ref, "screen", s.get("name") or "", standing="observed" if url else "inferred",
                        source=src(url, "screenshot" if s.get("shot") else "page"),
                        data={k: s.get(k) for k in ("purpose", "shows", "actions", "surface", "shot") if s.get(k)}))
    for f in d.get("features") or []:
        url = f.get("source") or ""
        out.append(item(ref, "action", f.get("name") or "", standing="observed" if url else "inferred",
                        source=src(url), data={k: f.get(k) for k in ("detail", "area", "where") if f.get(k)}))
    for e in d.get("entities") or []:
        out.append(item(ref, "record", e.get("name") or "", standing="inferred", source=src(None),
                        data={"fields": e.get("fields") or [], "links": e.get("links") or []}))
    for r in d.get("rules") or []:
        url = r.get("source") or ""
        out.append(item(ref, "rule", r.get("text") or "", standing="observed" if url else "inferred", source=src(url)))
    for r in d.get("roles") or []:
        out.append(item(ref, "role", r.get("name") or "", standing="inferred", source=src(None),
                        data={"does": r.get("does")}))
    for fl in d.get("flows") or []:
        out.append(item(ref, "flow", fl.get("name") or "", standing="derived", source=src(None),
                        data={"role": fl.get("role"), "goal": fl.get("goal"), "steps": fl.get("steps") or []}))
    for v in d.get("voices") or []:
        url = v.get("source") or ""
        out.append(item(ref, "voice", v.get("text") or "", standing="observed" if url else "inferred",
                        source=src(url), data={"kind": v.get("kind")}))
    for g in d.get("gaps") or []:
        out.append(item(ref, "gap", g.get("text") or "", standing="unknown", source=src(None)))
    return [i for i in out if i["text"]]


def counts(items: list[dict]) -> dict[str, int]:
    out = {s: 0 for s in STANDINGS}
    for i in items:
        out[i.get("standing") or "unknown"] = out.get(i.get("standing") or "unknown", 0) + 1
    return out


def brief(items: list[dict], limit: int = 60000) -> str:
    """The evidence for a model to read, grouped by kind, each line with its
    standing, its id and where it came from. Names, field names, enum values
    and labels are quoted; spans of page text and script never are — the
    capture does not keep them."""
    lines: list[str] = []
    for kind in KINDS:
        rows = [i for i in items if i.get("kind") == kind]
        if not rows:
            continue
        lines.append(f"\n## {kind} ({len(rows)})")
        for i in rows:
            srcs = ", ".join(f"{s.get('type')}{(' ' + s['url']) if s.get('url') else ''}" for s in (i.get("sources") or [])[:2])
            data = ""
            if i.get("data") not in (None, {}, []):
                data = " " + json.dumps(i["data"], default=str)[:600]
            lines.append(f"- [{i['standing']}] #{i['id']} {i['text']}{data} ({srcs})")
    text = "\n".join(lines).strip()
    return text if len(text) <= limit else text[:limit] + "\n… (cut short)"


__all__ = ["STANDINGS", "KINDS", "CAPTURED", "item", "merge", "from_dossier", "counts", "brief"]
