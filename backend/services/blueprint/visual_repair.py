"""Turn a render critique into re-compose briefs — the bridge that makes the
visual critic repair-driving, not merely reported.

The visual QA critic (``services.visual_qa_critic``) reviews screenshots of the
rendered pages and returns findings ``[{route, kind, severity, note}]``. Until
now those were written to a report and read by nobody — the autofix loop
dispatched on FUNCTIONAL faults only, so a page the critic called sparse,
duplicated or missing content shipped exactly as composed.

This maps each actionable finding onto the page that owns its route and phrases
it as a ``page_layouts`` repair brief — the same ``feedback`` a composer re-runs
against when the observer sends a node back. A route with no page, and
info-severity notes, drive nothing: a brief that names no subject re-composes
nothing, and advisory notes are not defects to loop on.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

#: info is advisory — surfaced, never a reason to re-compose. error and warn are
#: concrete defects the composer is asked to fix.
_ACTIONABLE_SEVERITIES = frozenset({"error", "warn"})


def _route_to_page_id(doc: Mapping[str, Any]) -> dict[str, str]:
    """Route template -> page id, for every live page that has both."""
    out: dict[str, str] = {}
    for p in doc.get("pages") or []:
        if not isinstance(p, dict):
            continue
        route = str(p.get("route") or "").strip()
        pid = str(p.get("id") or "").strip()
        if route and pid:
            out.setdefault(route, pid)
    return out


def _template_to_regex(template: str) -> re.Pattern[str]:
    """A route template (`/records/[id]/edit`) as a regex that also matches the
    concrete route a screenshot was taken at (`/records/42/edit`). Dynamic
    segments — `[id]`, `[...slug]` — match one-or-more path segments."""
    parts = []
    for seg in template.strip("/").split("/"):
        if seg.startswith("[") and seg.endswith("]"):
            parts.append(r"[^/]+")
        else:
            parts.append(re.escape(seg))
    return re.compile("^/" + "/".join(parts) + "/?$")


def _page_id_for_route(route: str, route_map: dict[str, str],
                       doc: Mapping[str, Any]) -> str | None:
    """The page a screenshotted route belongs to. Exact template match first,
    then the concrete route matched against each template's dynamic form."""
    route = (route or "").strip()
    if not route:
        return None
    if route in route_map:
        return route_map[route]
    for template, pid in route_map.items():
        if ("[" in template) and _template_to_regex(template).match(route):
            return pid
    return None


def repair_briefs_from_visual_qa(
    visual_qa: Mapping[str, Any] | None,
    doc: Mapping[str, Any],
) -> dict[str, str]:
    """``{page_id: brief}`` — one re-compose brief per page a visual review
    flagged with an actionable finding. Empty when nothing is actionable.

    The brief is composer-facing feedback: it names each rendered problem and
    asks for a re-composition that does not reproduce it. Pages are keyed by id
    because that is the ``page_layouts`` subject the scheduler re-runs.
    """
    findings = (visual_qa or {}).get("findings") or []
    route_map = _route_to_page_id(doc)

    by_page: dict[str, list[dict]] = {}
    for f in findings:
        if not isinstance(f, dict):
            continue
        if str(f.get("severity") or "warn") not in _ACTIONABLE_SEVERITIES:
            continue
        note = str(f.get("note") or "").strip()
        kind = str(f.get("kind") or "").strip()
        if not note or not kind:
            continue
        pid = _page_id_for_route(str(f.get("route") or ""), route_map, doc)
        if not pid:
            continue
        by_page.setdefault(pid, []).append({"kind": kind, "note": note})

    briefs: dict[str, str] = {}
    for pid, items in by_page.items():
        lines = "\n".join(f"  - {it['kind']}: {it['note']}" for it in items)
        briefs[pid] = (
            "A visual review of THIS page as it actually rendered found problems "
            "a reader would see:\n"
            f"{lines}\n\n"
            "Re-compose the page so each of these is fixed. These are how the "
            "screen looked, not guesses — do not reproduce them, and do not "
            "trade one for another (fixing the empty space by padding it with "
            "filler is not a fix)."
        )
    return briefs


__all__ = ["repair_briefs_from_visual_qa"]
