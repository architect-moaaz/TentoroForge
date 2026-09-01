"""Smith composing a screen — by calling the agent that already composes them.

Smith had one write move: rename an element. Asked to build a dashboard it
answered that nothing needed changing, having understood the request perfectly
and had nowhere to put it.

The composer it needed was already there. `page_layouts` composes one page per
subject, through A2UI with the authoring agent behind it, and `apply_change`
already implements §114 steps 3-7 — analyse impact, commit the Blueprint, run
the §72 sub-DAG. Neither was reachable from a conversation. This connects them.

NOTHING NEW COMPOSES ANYTHING HERE. `compose_route` builds the same `TaskSpec`
the orchestrator builds and hands it to the same executor, so a page Smith
composes and a page the build composed come from one code path. A second
composer would be a second answer to "what does this screen look like", and
the first thing to diverge.

AND THE BLUEPRINT STAYS THE RECORD. Both verbs end at `apply_change`, so the
artifact is committed before anything regenerates and the incremental DAG
re-projects from it. A seam that wrote `src/schemas/*.json` directly would
leave the Blueprint describing a different application, which is the
divergence §115 refuses.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)


class ComposeError(RuntimeError):
    """The request named something the Blueprint does not have."""


def _page_for_route(doc: dict, route: str) -> dict | None:
    """The page contract for a route, tolerant about how a user typed it."""
    want = (route or "").strip()
    if not want:
        return None
    if not want.startswith("/"):
        want = "/" + want
    pages = [p for p in (doc.get("pages") or []) if p.get("status") != "DEPRECATED"]

    for page in pages:
        if (page.get("route") or "") == want:
            return page
    # "/dashboard" for a page named Dashboard, "home" for "/" — a user names the
    # screen as often as the path, and refusing on punctuation would be pedantry.
    lowered = want.lstrip("/").lower()
    for page in pages:
        if str(page.get("name") or "").strip().lower() == lowered:
            return page
    if lowered in ("home", "index", "dashboard", ""):
        return next((p for p in pages if (p.get("route") or "") == "/"), None)
    return None


def compose_route(
    svc: Any,
    route: str,
    *,
    app_root: str | None = None,
    request: str = "",
    executor: Any = None,
    reasoning: Any = None,
) -> Any:
    """Compose the screen at `route` and commit it.

    Runs the `page_layouts` agent for exactly that page — the same executor,
    the same TaskSpec, the same A2UI path the build uses — then hands the
    proposals to `apply_change`.
    """
    from services.blueprint.executors import make_executor, tiered_router, RunUsage
    from services.blueprint.orchestrator import TaskSpec
    from services.smith.change import apply_change

    page = _page_for_route(svc.doc, route)
    if page is None:
        known = [p.get("route") for p in (svc.doc.get("pages") or [])][:8]
        raise ComposeError(
            f"there is no page at {route!r} in this application. "
            f"Routes it does have include: {', '.join(filter(None, known))}"
        )

    # The composition is the slow part of the turn — around a minute behind a
    # single message. `reasoning` is how that minute becomes legible: the
    # executor's stream was already open and its thinking events discarded.
    run = executor or make_executor(svc, tiered_router(reasoning=reasoning),
                                    usage=RunUsage(), reasoning=reasoning)
    spec = TaskSpec(task_id=f"smith-compose-{page['id']}", node="page_layouts",
                    agent="a2ui_pages", attempt=1, subject=page["id"],
                    feedback=None)

    result = run(spec)
    if not getattr(result, "proposals", None):
        # The composer declining is a real outcome and says so. Reporting it as
        # a success with nothing behind it is the failure this whole module is
        # a reaction to.
        raise ComposeError(
            f"the composer returned nothing for {page.get('route')}. "
            "Nothing has been changed."
        )

    return apply_change(
        svc,
        request or f"compose the screen at {page.get('route')}",
        proposals=list(result.proposals),
        interpretation=f"recompose {page.get('route')} ({page.get('pattern')})",
        agent="smith",
        app_root=app_root,
    )


def add_widgets(
    svc: Any,
    route: str,
    widgets: Sequence[str],
    *,
    app_root: str | None = None,
    request: str = "",
    executor: Any = None,
    reasoning: Any = None,
) -> Any:
    """Add named sections to a screen, by saying so in its contract first.

    NOT A PATCH ON THE TREE. The page contract is what a composition is written
    from, so the widgets are recorded there — in `primaryTasks`, which is
    already the free-text statement of what a user comes to this page to do —
    and then the page is composed again against the contract that now names
    them.

    Patching the rendered tree instead would put the widgets in the app and
    leave the Blueprint describing a page without them: the next composition
    would drop them, and nobody would know why. Recording intent and
    regenerating is §115, and it is also simply more likely to produce a page
    that hangs together than five components spliced into someone else's
    layout.
    """
    from services.blueprint.service import ARTIFACT_SECTIONS  # noqa: F401

    page = _page_for_route(svc.doc, route)
    if page is None:
        raise ComposeError(f"there is no page at {route!r} in this application.")

    wanted = [str(w).strip() for w in (widgets or []) if str(w).strip()]
    if not wanted:
        raise ComposeError("no widgets were named, so there is nothing to add.")

    tasks = list(page.get("primaryTasks") or [])
    added = [w for w in wanted if w not in tasks]
    if added:
        # Committed on its own, before composing. If the composition then fails
        # the contract still records what was asked for, and a retry composes
        # against it rather than starting from a page that never heard the
        # request.
        body = {k: v for k, v in page.items() if k != "id"}
        body["primaryTasks"] = tasks + added
        svc.upsert("pages", body, natural_key=str(page.get("route") or page["id"]))
        svc.save()
        logger.info("[smith] %s primaryTasks += %s", page.get("route"), added)

    return compose_route(
        svc, page.get("route") or route, app_root=app_root,
        request=request or f"add {', '.join(wanted)} to {page.get('route')}",
        executor=executor, reasoning=reasoning,
    )


# ── the tool seam ───────────────────────────────────────────────────────

#: Which verbs this module answers for. `run` is what the agent loop calls, so
#: an unknown verb has to be named rather than silently doing the default —
#: that silence is the whole failure this module exists to remove.
VERBS = ("compose_route", "add_widgets")


def run(output_dir: str, verb: str, *, route: str = "",
        widgets: Sequence[str] = (), request: str = "",
        reasoning: Any = None) -> dict:
    """One composition, from an `output_dir` — the shape a tool handler needs.

    THE ONLY ENTRY POINT WITH BOTH CALLERS ON IT. The ReAct loop dispatches by
    tool name and `smith_session.run_iteration` dispatches by verb; if each
    loaded the Blueprint and called `apply_change` its own way there would be
    two answers to "what does composing a route do", which is the defect shape
    this session has spent its time removing. Both go through here.

    Returns the `{applied, edited_paths, ...}` envelope the other write tools
    return. A refusal is `applied: False` with a `reason` — never an exception
    that the loop would render as "unknown error" and never a bare success.
    """
    from services.blueprint.service import BlueprintService

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": ("this project has no Blueprint yet, so there is no "
                           "screen to compose. It needs defining first.")}

    app_root = str(Path(output_dir) / "app")
    wanted = [str(w).strip() for w in (widgets or []) if str(w).strip()]
    try:
        if verb == "add_widgets":
            result = add_widgets(svc, route, wanted, app_root=app_root,
                                 request=request, reasoning=reasoning)
            did = f"added {', '.join(wanted)} to {route}"
        elif verb == "compose_route":
            result = compose_route(svc, route, app_root=app_root,
                                   request=request, reasoning=reasoning)
            did = f"composed {route}"
        else:
            return {"applied": False, "edited_paths": [],
                    "reason": f"unknown compose verb {verb!r}; "
                              f"expected one of {', '.join(VERBS)}"}
    except ComposeError as exc:
        # The composer declining is a real outcome and says so.
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith] %s %s failed", verb, route)
        return {"applied": False, "edited_paths": [],
                "reason": f"{type(exc).__name__}: {exc}"}

    # `committed` is what `apply_change` actually reports. An earlier caller
    # read `artifacts`, which ChangeResult does not have, so every successful
    # composition reported nothing changed.
    committed = sorted(getattr(result, "committed", None) or [])
    return {
        "applied": bool(getattr(result, "applied", False)),
        "edited_paths": committed,
        "diff_summary": did + (f" — {len(committed)} artifact(s)"
                               if committed else ""),
        "version": getattr(result, "version", 0),
        "reason": str(getattr(result, "reason", "") or ""),
    }
