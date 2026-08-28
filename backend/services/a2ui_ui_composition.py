"""Compose an application's whole UI through A2UI, one page at a time.

Why the whole set, and why still one page per call
--------------------------------------------------
Per-page authoring cannot decide the things §35 gives A2UI. Navigation
presentation and information density are properties of a *set*: a generated
bike shop rendered its "Jobs" heading twice, put its primary action in white on
white, and wrote its empty states in three different voices, because each page
was composed with no view of its siblings.

So the composer takes the page set. It does not take one call for it. Thirty-two
pages at the node counts A2UI produces will not fit one response, and a single
call is all-or-nothing: today's per-subject tolerance is what let a run finish
with 28 of 32 pages instead of none. Coherence comes from every call carrying
the same shared context — the page set, the design system, the UI registry §38
asks A2UI to reuse — not from cramming the app into one request.

What this does not decide
-------------------------
§35: "A2UI must not independently invent critical business rules." A2UI decides
that a page has a primary action and where it sits. Which workflow that action
dispatches is a Blueprint fact (``PageContract.dispatches``), and the binder
attaches it afterwards.

The binder is deterministic on purpose. ``data_sources``, ``gate_states`` and
``bind_workflows`` are pure functions over a tree and the Blueprint: a
``{{customers}}`` binding becomes a real fetch, four authored state subtrees
become one Conditional, a form gets its workflow. Making that a second agent
would reintroduce exactly the guessing that cost four page trees to
``action: {navigate}`` and one to ``preserveValues``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: A page A2UI could not compose leaves the deterministic composer to own that
#: route, exactly as `compose_page_via_a2ui` already does for one page.
PageComposer = Callable[..., dict]


def shared_context(doc: dict) -> str:
    """What every page in this application should be composed against.

    §37's design system and §38's UI registry, plus the page set itself. Passed
    to every call so the twelfth page knows what the first one did — which is
    the only way navigation presentation and density can be consistent without
    one enormous request.
    """
    import json

    design = doc.get("designSystem") or {}
    pages = [
        {"route": p.get("route"), "name": p.get("name"),
         "pattern": p.get("pattern"), "purpose": p.get("purpose")}
        for p in doc.get("pages") or []
    ]
    return json.dumps({
        "pages": pages,
        "designSystem": {k: design.get(k) for k in (
            "visualPersonality", "colors", "typography", "spacing", "radius",
            "informationDensity", "navigationApproach", "elevation",
        ) if design.get(k)},
        "uiRegistry": doc.get("uiRegistry") or [],
    }, indent=2, sort_keys=True)


def compose_ui_via_a2ui(
    output_dir: str,
    doc: dict,
    *,
    page_composer: Optional[PageComposer] = None,
    routes: list[str] | None = None,
) -> dict[str, Any]:
    """Compose every page of one application. Returns what each route did.

    One call per page, each carrying :func:`shared_context`, so a failure costs
    one route rather than the application. `applied: False` for a page is an
    ordinary outcome — the deterministic composer owns that route — and the
    summary says which, so a run that composed 28 of 32 pages does not read
    like one that composed all of them.
    """
    if page_composer is None:
        from services.a2ui_authority import compose_page_via_a2ui
        page_composer = compose_page_via_a2ui

    wanted = routes if routes is not None else [
        p.get("route") for p in doc.get("pages") or [] if p.get("route")
    ]
    context = shared_context(doc)
    by_pattern = {p.get("route"): (p.get("pattern") or "")
                  for p in doc.get("pages") or []}

    results: list[dict[str, Any]] = []
    for route in wanted:
        try:
            outcome = page_composer(
                output_dir, route, by_pattern.get(route, ""),
                shared_context=context,
            )
        except TypeError:
            # A composer that predates the shared context still composes; it
            # simply does so without knowing its siblings.
            outcome = page_composer(output_dir, route, by_pattern.get(route, ""))
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            # A composer that raises must not take the other pages with it.
            logger.warning("A2UI composition raised for %s: %s", route, exc)
            outcome = {"applied": False, "route": route, "reason": str(exc)}
        results.append(outcome)

    composed = [r["route"] for r in results if r.get("applied")]
    declined = {r.get("route"): r.get("reason") for r in results
                if not r.get("applied")}
    return {
        "composed": composed,
        "declined": declined,
        "pages": len(wanted),
        # Not "ok": composing none of them is a real outcome to report, not an
        # error to raise — every route still has a deterministic composer.
        "applied": bool(composed),
    }
