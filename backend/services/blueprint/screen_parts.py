"""Where a large screen is cut into files — decided from its sections.

ONE REPLY HAS A CEILING. The page writer writes a page's two files in one
reply, and a screen that holds five tables with their dialogs is five of
yesterday's pages in one file: near the writer's output limit, every repair
resending all of it, one broken dialog failing the whole screen. The planner
already says what a screen is made of (`pages[].sections`), and its main and
tab sections are the natural seams: a screen with `SPLIT_AT` or more of them
is written as a frame (`view.tsx`: header, tabs, where each part sits) and one
part per section (`parts/<key>.tsx`), each written, compiled and changed on
its own. A panel or a dialog belongs to the part it opens from.

Decided here, from the sections, with no model call — the same screen always
cuts the same way, and a change to the coupons tab knows it is
`parts/coupons.tsx`.
"""
from __future__ import annotations

import re
from typing import Any

#: Main and tab sections at which a screen is written in parts.
SPLIT_AT = 3

_NOT_A_NAME = re.compile(r"[^a-z0-9]+")


def part_key(section_key: Any) -> str:
    """A section's key as a file name: `Open tickets` → `open-tickets`."""
    return _NOT_A_NAME.sub("-", str(section_key or "").lower()).strip("-") or "part"


def component_name(key: str) -> str:
    """`open-tickets` → `OpenTicketsPart`, the name the frame imports it by."""
    return "".join(w.capitalize() for w in key.split("-") if w) + "Part"


def _norm(text: Any) -> str:
    return " ".join(_NOT_A_NAME.sub(" ", str(text or "").lower()).split())


def _workflow_entities(wf: dict) -> set[str]:
    return {str(s.get("entity")) for s in wf.get("steps") or [] if isinstance(s, dict) and s.get("entity")}


def screen_parts(doc: dict, page: dict) -> list[dict]:
    """The parts a screen is written in, or `[]` for a page written whole.

    Each part: `{key, component, label, sections, workflows}` — the sections
    it draws (its anchor first, then the panels and dialogs that open from it)
    and the ids of the workflows launched from the screen that it runs. A
    workflow no part claims is the frame's (`frame_workflows`)."""
    secs = [s for s in page.get("sections") or [] if isinstance(s, dict) and s.get("key")]
    anchors = [s for s in secs if str(s.get("placement") or "main") in ("main", "tab")]
    if len(anchors) < SPLIT_AT:
        return []
    parts: dict[str, dict] = {}
    for a in anchors:
        key = part_key(a["key"])
        while key in parts:                      # two sections keyed alike stay two files
            key += "-2"
        parts[key] = {"key": key, "component": component_name(key), "label": str(a.get("label") or key),
                      "anchor": str(a["key"]), "sections": [a], "workflows": []}
    by_anchor = {p["anchor"]: p for p in parts.values()}
    first = next(iter(parts.values()))
    for s in secs:
        if any(s is a for a in anchors):
            continue
        home = by_anchor.get(str(s.get("opensFrom") or "")) or next(
            (p for p in parts.values() if s.get("entity") and p["sections"][0].get("entity") == s.get("entity")),
            first)
        home["sections"].append(s)
    # WHO RUNS WHAT: a workflow named as a section's action, or one that
    # writes the records a part adds; anything else is run by the frame.
    for wf in doc.get("workflows") or []:
        if not isinstance(wf, dict) or wf.get("status") == "DEPRECATED" \
                or str(page.get("id")) not in [str(x) for x in wf.get("launchedFrom") or []]:
            continue
        name = _norm(wf.get("name"))
        owner = next((p for p in parts.values()
                      if any(_norm(a) == name for sec in p["sections"] for a in sec.get("actions") or [])), None)
        if owner is None:
            touched = _workflow_entities(wf)
            owner = next((p for p in parts.values()
                          if any(sec.get("addsHere") and str(sec.get("entity") or "") in touched
                                 for sec in p["sections"])), None)
        if owner is None:
            touched = _workflow_entities(wf)
            owner = next((p for p in parts.values() if str(p["sections"][0].get("entity") or "") in touched), None)
        if owner is not None:
            owner["workflows"].append(str(wf.get("id")))
    return list(parts.values())


def frame_workflows(doc: dict, page: dict, parts: list[dict]) -> list[str]:
    """The workflows launched from the screen that no part runs."""
    claimed = {w for p in parts for w in p["workflows"]}
    return [str(w.get("id")) for w in doc.get("workflows") or []
            if isinstance(w, dict) and w.get("status") != "DEPRECATED"
            and str(page.get("id")) in [str(x) for x in w.get("launchedFrom") or []]
            and str(w.get("id")) not in claimed]


def stub_part(component: str) -> str:
    """A part not written yet, so the frame compiles before its parts exist."""
    return ('"use client";\n\n'
            f"export default function {component}(_props: {{ data: unknown }}) {{\n  return null;\n}}\n")
