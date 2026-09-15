"""Disconnect a design and compose the screens from components.

WHAT THIS UNDOES. `connect_figma` and `connect_uxpilot` record a design source
and, under a reference, `page_contracts` binds its frames to pages as
`figmaFrame`; `page_layouts` then builds those pages from the drawing. When the
drawing is the wrong one for the page — fifteen identically named frames bound
in file order, every page a single text node of somebody else's screen — the
way back is not fifteen `compose_route` turns, each of which would rebuild the
page from the same frame again. It is one change: the source goes, no page
names a frame, the drawn layouts go, and the composer runs over the pages that
lost them.

WHY A VERB AND NOT A HAND EDIT. The first time this was needed (2026-09-13,
Criterion Refunds v2) it was done by a script against the Blueprint files:
`figmaFrame` is a pinned page field, so no agent proposal can remove it, and no
verb existed. A script is a second answer to what the Blueprint says, and it
does not appear in the change history unless someone remembers to commit it.
This module is the one answer, and `smith_session` routes the words
"disconnect the design" to it.

WHAT IT DOES NOT TOUCH. Requirements, entities, rules, workflows, navigation:
the design was evidence for those and they stand on their own. The stored
extraction under `.forge/figma/` stays too — it is evidence of what was
connected, and a later reconnect reuses its id.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

#: Layouts a design composed. Anything else was composed from components and
#: is kept — a page that never named a frame is not part of this change.
DRAWN_BY = frozenset({"figma", "uxpilot"})


def disconnect(svc: Any, request: str, *, interpretation: str = "") -> dict[str, Any]:
    """Remove every design source and every page's frame; commit; say what changed.

    Returns ``{"applied": False, "reason"}`` when nothing is connected —
    there is nothing to undo, and a commit with no diff is a version that says
    nothing.
    """
    sources = [str(s.get("id") or "") for s in (svc.doc.get("designSources") or [])]
    bound = [p for p in (svc.doc.get("pages") or []) if p.get("figmaFrame")]
    if not sources and not bound:
        return {"applied": False, "reason": "no design is connected to this application"}
    before = svc.snapshot()
    unbound = [str(p.get("id")) for p in bound]
    for page in bound:
        page.pop("figmaFrame", None)
    layouts = list(svc.doc.get("pageLayouts") or [])
    kept = [l for l in layouts if str(l.get("composedBy") or "") not in DRAWN_BY]
    dropped = len(layouts) - len(kept)
    svc.doc["pageLayouts"] = kept
    svc.doc["designSources"] = []
    record = svc.commit(
        user_request=request,
        smith_interpretation=interpretation or (
            f"Disconnected {', '.join(s for s in sources if s) or 'the design'}: "
            f"{len(unbound)} page(s) no longer name a frame and {dropped} drawn "
            "layout(s) are retired; every screen is composed from the component "
            "library."
        ),
        before=before,
        affected=unbound,
    )
    return {
        "applied": True,
        "sources": [s for s in sources if s],
        "unbound": unbound,
        "dropped_layouts": dropped,
        "version": record.get("version"),
        "plan": recomposition_plan(),
    }


def recomposition_plan() -> list[str]:
    """The sub-DAG that follows: compose the pages, then everything downstream.

    Declared rather than derived. `incremental_plan` over "the pages changed"
    seeds every node that writes `pages` — the page-set planner among them —
    and re-authoring the page set is exactly the churn this change exists to
    avoid. The pages are the same pages; only what they are built from
    changed, and that is `page_layouts` and what consumes it. Verification is
    always in (§75).
    """
    from services.blueprint.orchestrator import descendants, levels

    order = [k for level in levels() for k in level]
    want = ({"page_layouts"} | descendants("page_layouts")
            | {"verification"} | descendants("verification"))
    return [k for k in order if k in want]


def recompose(svc: Any, plan: list[str], *, request: str, app_root: str,
              reasoning: Callable[..., None] | None = None,
              observer: Callable[[dict], None] | None = None) -> Any:
    """Run the plan through the same executor the build uses (§116)."""
    from services.blueprint.executors import RunUsage, make_executor, tiered_router
    from services.blueprint.observer import anthropic_observer
    from services.blueprint.orchestrator import run

    usage = RunUsage()
    router = tiered_router(reasoning=reasoning)
    executor = make_executor(svc, router, usage=usage, reasoning=reasoning)
    watcher = anthropic_observer(router, usage=usage)
    return run(svc, executor, plan=plan, commit=True, user_request=request,
               app_root=app_root, observer=observer, observer_agent=watcher)


def disconnect_and_recompose(output_dir: str | Path, request: str, *,
                             reasoning: Callable[..., None] | None = None) -> dict[str, Any]:
    """The whole move, for a chat turn: load, disconnect, recompose, report."""
    from services.blueprint.service import BlueprintService
    from services.llm_client import tell

    svc = BlueprintService.load(output_dir=str(output_dir))
    out = disconnect(svc, request)
    if not out.get("applied"):
        return out
    tell(reasoning, (f"Disconnected {', '.join(out['sources']) or 'the design'}; "
                     f"composing {len(out['unbound'])} screen(s) from the component library."),
         "step")
    report = recompose(svc, out["plan"], request=request,
                       app_root=str(Path(output_dir) / "app"), reasoning=reasoning)
    out["completed"] = list(getattr(report, "completed", []) or [])
    out["failed"] = list(getattr(report, "failed", []) or [])
    return out
