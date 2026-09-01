"""The entry point always exists.

A page whose composition is refused leaves no layout, the projection writes no
schema, and the route falls through to the catch-all — a 404. `_unbuilt_pages`
reports that, correctly, and the run carries on: one missing route out of fifty
is a defect, not a reason to throw the application away.

The landing route is the exception, and it is a difference in kind rather than
degree. Every other 404 is a page a user might reach; this one is the page they
arrive on. An application whose front door 404s is not a working application
with one page missing — measured on the legislative platform, a build that
compiled cleanly, passed verification, and opened on "This page could not be
found".

WHAT THIS IS NOT. It does not touch a composition the floor refused, and it
never overwrites a layout that exists. It runs only when the landing page has
NO layout at all — the difference between repairing the model's work and
supplying something where the model supplied nothing. A composed page that was
rejected stays rejected; that judgement is `check_pattern_templates`' and it
keeps it.

MARKED FOR WHAT IT IS. The layout records `composedBy: "deterministic"`, beside
A2UI's "a2ui" and the authoring agent's "agent". A page nobody could compose
and a page composed well must never be indistinguishable in the Blueprint —
that distinction is why `composedBy` exists at all.
"""

from __future__ import annotations

from typing import Any

#: What the landing page links to, in the order a reader would want them: the
#: navigation the application declared for itself. Falling back to entity list
#: routes only when navigation is empty, because a hand-declared nav says
#: something about priority that a list of tables does not.
_MAX_TILES = 12


def _landing_page(doc: dict) -> dict | None:
    """The page a user arrives on, by the Blueprint's own reckoning."""
    nav = doc.get("navigation") or {}
    pages = [p for p in (doc.get("pages") or []) if p.get("status") != "DEPRECATED"]

    for key in ("landing", "home", "root"):
        route = nav.get(key)
        if isinstance(route, str) and route:
            hit = next((p for p in pages if p.get("route") == route), None)
            if hit:
                return hit
    return next((p for p in pages if p.get("route") == "/"), None)


def _destinations(doc: dict, landing_id: str) -> list[dict]:
    """Where the entry point should let a user go.

    Read from the navigation tree first — it is the application's own statement
    about what matters — and from list pages otherwise. Either way these are
    routes that EXIST: a tile pointing at a page nobody composed would trade a
    404 on arrival for a 404 one click later.
    """
    pages = {p.get("id"): p for p in (doc.get("pages") or [])}
    composed = {l.get("pageId") or l.get("page")
                for l in (doc.get("pageLayouts") or [])}

    out: list[dict] = []
    seen: set[str] = set()

    def add(page: dict | None) -> None:
        if not page or page.get("id") in seen or page.get("id") == landing_id:
            return
        # Only somewhere a user can actually land.
        if page.get("id") not in composed:
            return
        route = page.get("route") or ""
        if not route or "[" in route or route.endswith("/new"):
            return
        seen.add(page.get("id"))
        out.append({"route": route,
                    "label": str(page.get("name") or route).strip()})

    def walk(nodes: Any, depth: int = 0) -> None:
        if depth > 4 or not isinstance(nodes, list):
            return
        for n in nodes:
            if not isinstance(n, dict):
                continue
            add(pages.get(n.get("page")))
            walk(n.get("children"), depth + 1)

    walk(((doc.get("navigation") or {}).get("tree")) or [])
    if not out:
        for p in (doc.get("pages") or []):
            if p.get("pattern") in ("entity_list", "dashboard", "data_explorer"):
                add(p)
    return out[:_MAX_TILES]


def compose_landing(doc: dict) -> dict | None:
    """A layout for the entry point, from what the Blueprint already knows.

    Returns the `pageLayouts` body, or None when the landing page already has
    a layout or the Blueprint has no landing page to speak of.
    """
    page = _landing_page(doc)
    if not page:
        return None

    have = {l.get("pageId") or l.get("page")
            for l in (doc.get("pageLayouts") or [])}
    if page.get("id") in have:
        return None

    dests = _destinations(doc, page.get("id"))
    app = (doc.get("application") or {}).get("name") or ""
    title = str(page.get("name") or app or "Home")

    children: list[dict] = [
        {"type": "Heading", "props": {"text": title, "level": 1}},
    ]
    purpose = str(page.get("purpose") or "").strip()
    if purpose:
        children.append({"type": "Text", "props": {"text": purpose}})

    if dests:
        children.append({
            "type": "Grid",
            "props": {"columns": 3},
            "children": [
                {"type": "Card",
                 "props": {"title": d["label"]},
                 "children": [
                     {"type": "Link",
                      "props": {"href": d["route"], "text": d["label"]}},
                 ]}
                for d in dests
            ],
        })
    else:
        # Nothing composed to link to. Say so rather than rendering an empty
        # grid that reads as a page still loading.
        children.append({
            "type": "EmptyState",
            "props": {"title": title,
                      "description": "This application has no other pages yet."},
        })

    return {
        "page": page.get("id"),
        "root": {"type": "Stack", "children": children},
        "dataSources": [],
        "composedBy": "deterministic",
        "rationale": ("the entry point had no composed layout; assembled from "
                      "navigation so the application does not open on a 404"),
        "requirements": list(page.get("requirements") or []),
    }


def ensure_landing_layout(svc: Any) -> dict | None:
    """Give the entry point a layout when nothing composed one.

    Writes through `svc.upsert`, so it becomes a Blueprint artifact like any
    other and the frontend projection renders it from there. A composer that
    wrote the page file directly would leave the Blueprint saying something
    different, which is the divergence §115 exists to refuse.
    """
    body = compose_landing(svc.doc)
    if body is None:
        return None
    svc.upsert("pageLayouts", body, natural_key=str(body["page"]))
    return body
