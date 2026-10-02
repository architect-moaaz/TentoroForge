"""What a page answers to, and which screens use a record — read from links
the Blueprint already has, for the agents that change one without the other.

A page carries no requirement ids, and a requirement names no page; they meet
through the page's module, the processes launched from it, and the rules on
the records it shows. The page writer never saw them, so "dish names must be
unique" — a requirement and a rule on FoodItem — was invisible to the writer
of the dish form (2026-10-02).

The data model agent sees no pages at all (its contract slice), so a field it
renamed in passing (`image` → `photo`) broke the screens that read it, found
only when the push failed. Which screens read which fields is said to it as
part of the change, not as a section it could write into.
"""
from __future__ import annotations

import re
from typing import Any


def _live(items: Any) -> list[dict]:
    return [x for x in items or [] if isinstance(x, dict)
            and str(x.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]


def _page_entities(page: dict) -> set[str]:
    data = page.get("data") or {}
    return {str(x) for x in [data.get("primaryEntity"), *(data.get("supportingEntities") or [])] if x}


def page_requirements(doc: dict, page: dict, *, limit: int = 12) -> list[dict]:
    """[{id, statement}] the page answers to: its module's, those of the
    processes launched from it, and those of the rules on its records."""
    pid = str(page.get("id") or "")
    ids: list[str] = []

    def add(refs: Any) -> None:
        for r in refs or []:
            if str(r).startswith("REQ-") and str(r) not in ids:
                ids.append(str(r))

    for m in _live(doc.get("modules")):
        if str(m.get("id")) == str(page.get("module") or ""):
            add(m.get("requirements"))
    for w in _live(doc.get("workflows")):
        if pid in [str(x) for x in w.get("launchedFrom") or []]:
            add(w.get("requirements"))
    ents = _page_entities(page)
    for r in _live(doc.get("businessRules")):
        on = {str(r.get("entity") or "")} | {str(x) for x in r.get("appliesTo") or []}
        if ents & on or pid in on:
            add(r.get("requirements"))
    reqs = {str(r.get("id")): r for r in _live(doc.get("requirements"))}
    out = []
    for rid in ids:
        r = reqs.get(rid)
        if r:
            said = str(r.get("description") or r.get("statement") or r.get("name") or "").strip()
            if said:
                out.append({"id": rid, "statement": said})
    return out[:limit]


def entity_usage(doc: dict) -> dict[str, list[dict]]:
    """{entity name: [{route, fields}]} — the screens that show or change each
    record, and which of its fields their code or content plan reads."""
    code = {str(c.get("page")): str(c.get("load") or "") + "\n" + str(c.get("view") or "")
            for c in doc.get("pageCode") or [] if isinstance(c, dict)}
    out: dict[str, list[dict]] = {}
    for e in _live((doc.get("data") or {}).get("entities")):
        eid, name = str(e.get("id")), str(e.get("name") or "")
        fields = [str(f.get("name")) for f in e.get("fields") or [] if isinstance(f, dict) and f.get("name")]
        for p in _live(doc.get("pages")):
            text = code.get(str(p.get("id")), "")
            plan = str(p.get("content") or "")
            if eid not in _page_entities(p) and not re.search(rf"[\"']{re.escape(name)}[\"']", text):
                continue
            used = [f for f in fields if f != "id" and (re.search(rf"\b{re.escape(f)}\b", text) or f in plan)]
            out.setdefault(name, []).append({"route": str(p.get("route") or p.get("id")), "fields": used})
    return out


def usage_brief(doc: dict, *, limit: int = 40) -> str:
    """The screens that use each record, as lines for an agent's brief."""
    lines = []
    for name, uses in entity_usage(doc).items():
        for u in uses:
            lines.append(f"- {name} on {u['route']}" + (f": {', '.join(u['fields'])}" if u["fields"] else ""))
    if not lines:
        return ""
    return ("Screens that already use these records — a field renamed, retyped or removed breaks "
            "them, so keep every field they read unless the ask is to change it:\n"
            + "\n".join(lines[:limit]))
