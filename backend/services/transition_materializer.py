"""Transition materializer — inject the UI the contracts promised (B1+B2).

The delivery gate (services.delivery_gate) turned two silent failure
classes into reported errors:

- ``transition_trigger_missing`` — nav-flow declares a transition fired
  by ``button:Back`` on a page, but no such button exists in the page
  schema. The transition is dead data.
- ``workflow_launcher_missing`` — plan declares a workflow with trigger
  ``button on <Page>``, but no page renders a launcher. The feature is
  unreachable.

This pass is the *repair* those errors point at. It runs right before
the gate so strict mode converges instead of failing:

**B1 — transition buttons.** For every ``button:<Label>`` transition
whose source page lacks the button, inject a deterministic Button with
the declared label navigating to the transition's target route. The
injected node uses the exact contract the engine already interprets
(``onClick: {action: "navigate", target}`` — same shape the shipped
Documents-page "Upload" button uses).

**B2 — workflow launcher buttons.** For every plan workflow with a
``button on <PageName>`` trigger and no shipped launcher:
  1. Resolve the on-disk workflow (canon name match against
     ``workflows/*.json`` ids/names). **No on-disk workflow → skip** —
     injecting a button that dispatches nothing would convert a visible
     gate error into an invisible runtime failure, which is strictly
     worse. The gate keeps reporting it as unrepairable.
  2. Resolve ``<PageName>`` ("DocumentDetailPage") to a shipped page by
     matching kind + entity tokens against plan pages.
  3. Inject a Button with ``props.workflow = <on-disk name>`` (the
     dispatch seam the library Button already implements).

Placement: buttons whose label reads as back-navigation ("back",
"cancel", "return") are PREPENDED to the page root's children (top of
page, where users look for wayfinding); everything else is APPENDED
(actions live below content). Both idempotent — presence of a matching
button (same check the gate uses) short-circuits re-injection.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from services.delivery_gate import (
    _BUTTON_TYPES,
    _canon,
    _load_nav_flow,
    _load_page_schemas,
    _load_plan,
    _node_label,
    _node_type,
    _norm_route,
    _UI_TRIGGER_PREFIXES,
    _walk,
    _workflow_refs_in,
)

logger = logging.getLogger(__name__)

_BACKISH = ("back", "cancel", "return", "close")


# ══════════════════════════════════════════════════════════════════
# Shared: schema file resolution + safe write + node injection
# ══════════════════════════════════════════════════════════════════

def _schema_path_for_route(root: Path, route: str) -> Path | None:
    """Map a route to its schema file via the same layout the registry
    uses: ``/documents/[id]`` → ``src/schemas/documents/[id].json``,
    ``/`` → ``index.json``."""
    sdir = root / "src" / "schemas"
    norm = _norm_route(route)
    if norm == "/":
        p = sdir / "index.json"
        if p.is_file():
            return p
    else:
        # Try both bracket conventions on disk.
        for candidate in (norm, norm.replace("{", "[").replace("}", "]")):
            p = sdir / (candidate.lstrip("/") + ".json")
            if p.is_file():
                return p
    # Filename convention missed — fall back to the schema's own declared
    # route. The root route in particular ships as home.json in some
    # layouts (fleet commerce-cart), and shell.json also claims "/" but
    # is chrome, never a page.
    for p in sorted(sdir.rglob("*.json")):
        if p.name == "shell.json":
            continue
        doc = _load_doc(p)
        if doc and _norm_route(str(doc.get("route") or "")) == norm:
            return p
    return None


def _load_doc(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _write_doc(path: Path, doc: dict) -> bool:
    try:
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[materializer] write failed %s: %s", path, exc)
        return False


def _injection_container(doc: dict) -> list | None:
    """The children list we can safely inject into: the root's children,
    else the first descendant carrying a children list. None → page has
    no injectable container (e.g. bare leaf root) — caller skips."""
    node = doc.get("root")
    if not isinstance(node, dict):
        return None
    kids = node.get("children")
    if isinstance(kids, list):
        return kids
    for n in _walk(node):
        kids = n.get("children")
        if isinstance(kids, list):
            return kids
    return None


def _has_button_labeled(doc: dict, label: str) -> bool:
    want = label.strip().lower()
    return any(
        _node_type(n) in _BUTTON_TYPES and _node_label(n).lower() == want
        for n in _walk(doc)
    )


def _humanize(name: str) -> str:
    """``ReprocessDocumentWorkflow`` → ``Reprocess Document``."""
    s = re.sub(r"[Ww]orkflow$", "", str(name or "").strip())
    s = re.sub(r"[_\-]+", " ", s)
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    return " ".join(w.capitalize() if w.islower() else w for w in s.split()).strip()


# ══════════════════════════════════════════════════════════════════
# B1 — transition buttons
# ══════════════════════════════════════════════════════════════════

def materialize_transitions(output_dir: str | Path) -> dict:
    """Inject buttons for ``button:<Label>`` transitions whose source
    page lacks them. Returns ``{injected: [...], skipped: [...]}``."""
    root = Path(output_dir)
    nav_flow = _load_nav_flow(root)
    injected: list[dict] = []
    skipped: list[dict] = []

    page_route_by_id = {
        str(e.get("id")): str(e.get("route") or "")
        for e in (nav_flow.get("pages") or []) if isinstance(e, dict)
    }

    for t in nav_flow.get("transitions") or []:
        if not isinstance(t, dict):
            continue
        trigger = str(t.get("trigger") or "")
        if not trigger.startswith("button:"):
            continue
        label = trigger.split(":", 1)[1].strip()
        src_route = page_route_by_id.get(str(t.get("from")))
        dst_route = page_route_by_id.get(str(t.get("to")))
        if not label or not src_route or not dst_route:
            skipped.append({"transition": t.get("id"), "reason": "unresolvable endpoints"})
            continue

        path = _schema_path_for_route(root, src_route)
        if path is None:
            # Page itself missing — that's planned_page_missing territory,
            # not ours. add_page owns that repair.
            skipped.append({"transition": t.get("id"),
                            "reason": f"source schema not on disk ({src_route})"})
            continue
        doc = _load_doc(path)
        if doc is None:
            skipped.append({"transition": t.get("id"), "reason": "unreadable schema"})
            continue
        if _has_button_labeled(doc, label):
            continue  # already satisfied — idempotency
        container = _injection_container(doc)
        if container is None:
            skipped.append({"transition": t.get("id"), "reason": "no injectable container"})
            continue

        button = {
            "id": f"mat_btn_{t.get('id') or _canon(label)}",
            "type": "Button",
            "props": {
                "label": label,
                # Wayfinding buttons stay visually quiet — the page's own
                # primary action keeps the accent.
                "variant": "outline",
                "onClick": {"action": "navigate", "target": dst_route},
            },
        }
        if label.lower() in _BACKISH:
            container.insert(0, button)
        else:
            container.append(button)
        if _write_doc(path, doc):
            injected.append({"transition": t.get("id"), "route": src_route,
                             "label": label, "target": dst_route})
            logger.info("[materializer] injected %r button on %s → %s",
                        label, src_route, dst_route)
    return {"injected": injected, "skipped": skipped}


# ══════════════════════════════════════════════════════════════════
# B2 — workflow launcher buttons
# ══════════════════════════════════════════════════════════════════

def _on_disk_workflows(root: Path) -> dict[str, str]:
    """{canon: dispatch_name} for every workflows/*.json. Dispatch name
    is the workflow's ``name`` field — the identifier the execute route
    resolves (the shipped upload form dispatches ``ProcessDocument``,
    not the file id)."""
    out: dict[str, str] = {}
    wdir = root / "workflows"
    if not wdir.is_dir():
        return out
    for p in sorted(wdir.glob("*.json")):
        doc = _load_doc(p)
        if not doc:
            continue
        name = str(doc.get("name") or doc.get("id") or p.stem)
        for form in (doc.get("id"), doc.get("name"), p.stem):
            if form:
                out[_canon(str(form))] = name
    return out


_KIND_WORDS = {"detail", "list", "dashboard", "search", "upload", "form",
               "create", "edit", "settings"}


def _resolve_page_route(page_name: str, plan: dict) -> str | None:
    """``DocumentDetailPage`` → the plan page whose kind + entity tokens
    match best. Requires BOTH an entity-token hit and (when the name
    carries a kind word) a kind hit — a weak single-signal match risks
    dropping an action button on an unrelated page."""
    # Exact plan-page NAME match first — planner triggers use the plan's
    # own page names verbatim ("button on StorefrontPage"), and token
    # matching against ROUTES can't resolve names whose route carries no
    # text at all (StorefrontPage → "/", the fleet commerce-cart case).
    want = _canon(page_name or "")
    if want:
        for pg in plan.get("pages") or []:
            if isinstance(pg, dict) and pg.get("route") and \
                    _canon(str(pg.get("name") or "")) == want:
                return str(pg["route"])
    tokens = [w.lower() for w in re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+", page_name or "")]
    tokens = [t for t in tokens if t != "page"]
    if not tokens:
        return None
    kind_wanted = next((t for t in tokens if t in _KIND_WORDS), None)
    entity_tokens = [t for t in tokens if t not in _KIND_WORDS]

    best: tuple[int, str] | None = None
    for pg in plan.get("pages") or []:
        if not isinstance(pg, dict) or not pg.get("route"):
            continue
        route = str(pg["route"])
        kind = str(pg.get("kind") or pg.get("type") or "").lower()
        route_lc = route.lower()
        score = 0
        entity_hit = any(
            t in route_lc or (t.rstrip("s") and t.rstrip("s") in route_lc)
            for t in entity_tokens
        )
        if entity_hit:
            score += 1
        if kind_wanted and kind == kind_wanted:
            score += 1
        # Param routes are the natural home of "detail" pages even when
        # the plan kind is missing.
        if kind_wanted == "detail" and "[" in route:
            score += 1
        if not entity_hit:
            continue
        if kind_wanted and score < 2:
            continue
        if best is None or score > best[0]:
            best = (score, route)
    return best[1] if best else None


_LAUNCH_VERBS = {
    "create", "add", "book", "cancel", "update", "delete", "mark", "submit",
    "join", "subscribe", "unsubscribe", "reassign", "adjust", "retry", "flag",
    "ingest", "schedule", "reject", "shortlist", "approve", "send", "generate",
    "assign", "complete", "close", "open", "archive", "start", "stop",
    "pause", "resume", "publish", "upload", "process", "run", "export",
    "import",
}


def _entity_page_candidates(wf: dict) -> list[str]:
    """Page-name candidates derived from the workflow itself, for triggers
    that name no page: explicit entity fields, tables its steps touch (in
    step order — the first table is the primary subject), and the workflow
    name minus its 'Workflow' suffix and leading verb."""
    out: list[str] = []
    seen: set[str] = set()

    def add(v: Any) -> None:
        v = str(v or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)

    for key in ("entity", "data_model", "table"):
        add(wf.get(key))
    for step in wf.get("steps") or []:
        if isinstance(step, dict):
            cfg = step.get("config") if isinstance(step.get("config"), dict) \
                else step
            add(cfg.get("table"))
    name = re.sub(r"Workflow$", "", str(wf.get("name") or ""))
    tokens = re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+", name)
    if len(tokens) > 1 and tokens[0].lower() in _LAUNCH_VERBS:
        add("".join(tokens[1:]))
    add(name)
    return out


def _landing_route(plan: dict) -> str | None:
    """The app's landing surface — "/" when it exists, else the first
    dashboard-shaped page. Used only as the launcher anchor of last
    resort for workflows whose entity has no page at all."""
    from services.dashboard_authority import is_dashboard_page
    pages = [p for p in plan.get("pages") or [] if isinstance(p, dict)]
    for pg in pages:
        if str(pg.get("route") or "").strip() in ("/", ""):
            if pg.get("route"):
                return "/"
    for pg in pages:
        if is_dashboard_page(pg) and pg.get("route"):
            return str(pg["route"])
    return None


def _is_record_scoped(wf: dict) -> bool:
    """True when the workflow's steps reference an existing record —
    its launcher belongs on a detail page where that record is in scope."""
    blob = json.dumps(wf.get("steps") or [])
    return "recordId" in blob or "{{id}}" in blob


def materialize_workflow_launchers(output_dir: str | Path) -> dict:
    """Inject dispatch Buttons for plan workflows triggered by
    ``button on <Page>`` that shipped without any launcher."""
    root = Path(output_dir)
    plan = _load_plan(root)
    schemas = _load_page_schemas(root)
    disk_workflows = _on_disk_workflows(root)

    shipped_refs: set[str] = set()
    for _r, doc in schemas:
        shipped_refs |= _workflow_refs_in(doc)

    injected: list[dict] = []
    skipped: list[dict] = []

    for wf in plan.get("workflows") or []:
        if not isinstance(wf, dict) or not wf.get("name"):
            continue
        name = str(wf["name"])
        trigger = wf.get("trigger")
        trigger_str = (
            trigger if isinstance(trigger, str)
            else str((trigger or {}).get("type") or "") if isinstance(trigger, dict)
            else ""
        ).strip()
        low = trigger_str.lower()
        if not low.startswith(_UI_TRIGGER_PREFIXES) or low.startswith("form"):
            # Forms are workflow_launch_forms' job. Everything else the
            # delivery gate counts as UI-triggered — "button on X", bare
            # "manual", "manual on <Entity>", "user ..." — is ours: the
            # gate demands a launcher for all of them, so all of them
            # must have a deterministic anchor here.
            continue
        if _canon(name) in shipped_refs:
            continue  # launcher exists — nothing to do

        dispatch_name = disk_workflows.get(_canon(name))
        if dispatch_name is None:
            skipped.append({
                "workflow": name,
                "reason": "no on-disk workflow definition — injecting a dead "
                          "dispatch button would hide the real gap",
            })
            continue

        # "button on DocumentDetailPage" → page-name token after "on".
        # Triggers may offer alternatives ("button on StorefrontPage or
        # PlantDetailPage") — try each until one resolves.
        m = re.search(r"\bon\s+(.+)$", trigger_str, re.IGNORECASE)
        candidates = re.split(r"\s+or\s+|,", m.group(1), flags=re.IGNORECASE) \
            if m else []
        page_name = ""
        route = None
        for cand in candidates:
            cand = cand.strip().split()[0] if cand.strip() else ""
            if not cand:
                continue
            route = _resolve_page_route(cand, plan)
            if route is not None:
                page_name = cand
                break
        named_page_explicitly = any(
            c.strip().split()[0].lower().endswith("page")
            for c in candidates if c.strip()
        )
        if route is None and named_page_explicitly:
            # The planner named a specific Page and it doesn't exist —
            # guessing a different page would hide that gap. Skip and
            # let the gate surface it.
            skipped.append({"workflow": name,
                            "reason": f"cannot resolve trigger page(s) "
                                      f"{[c.strip() for c in candidates]!r}"})
            continue
        if route is None:
            # No page named at all (bare "manual") or the clause names an
            # ENTITY, not a page ("manual on DriveApplication"). Anchor on
            # the workflow's own entity instead: explicit entity fields,
            # then step tables, then the name minus its leading verb.
            # Record-scoped workflows prefer the entity's detail page so
            # the dispatch has a record in context.
            record_scoped = _is_record_scoped(wf)
            for cand in _entity_page_candidates(wf):
                probes = [f"{cand}Detail", cand] if record_scoped else [cand]
                for probe in probes:
                    route = _resolve_page_route(probe, plan)
                    if route is not None:
                        page_name = cand
                        break
                if route is not None:
                    break
        if route is None:
            # Last resort: the LANDING surface. A cluttered dashboard
            # button beats an unreachable feature — and the plan
            # validator's workflow_entity_has_page rule pushes the
            # planner to give the entity a real page next time.
            route = _landing_route(plan)
        if route is None:
            skipped.append({"workflow": name,
                            "reason": f"cannot resolve trigger page(s) "
                                      f"{[c.strip() for c in candidates]!r} "
                                      f"or any entity page for {name!r}"})
            continue
        path = _schema_path_for_route(root, route)
        if path is None:
            skipped.append({"workflow": name,
                            "reason": f"resolved page {route!r} has no schema on disk"})
            continue
        doc = _load_doc(path)
        if doc is None:
            skipped.append({"workflow": name, "reason": "unreadable schema"})
            continue
        label = _humanize(name)
        if _has_button_labeled(doc, label):
            continue
        container = _injection_container(doc)
        if container is None:
            skipped.append({"workflow": name, "reason": "no injectable container"})
            continue

        container.append({
            "id": f"mat_wf_{_canon(name)}",
            "type": "Button",
            "props": {
                "label": label,
                "variant": "outline",
                "workflow": dispatch_name,
            },
        })
        if _write_doc(path, doc):
            injected.append({"workflow": name, "route": route,
                             "label": label, "dispatch": dispatch_name})
            logger.info("[materializer] injected launcher %r on %s (dispatch=%s)",
                        label, route, dispatch_name)
    return {"injected": injected, "skipped": skipped}


def repoint_dead_form_refs(output_dir: str | Path) -> dict:
    """B3 — Forms whose ``props.workflow`` resolves to NO on-disk
    workflow are dead submits. When the plan declares a form_submit
    workflow whose trigger page resolves to that form's page, repoint
    the form at the on-disk workflow name. (Fleet doc-intel case: the
    upload form shipped dispatching phantom 'UploadDocument' while the
    plan's RunOcrPipeline declares form_submit on DocumentUploadPage.)
    Only DEAD refs are touched — a form already dispatching a real
    workflow is authoritative."""
    root = Path(output_dir)
    plan = _load_plan(root)
    disk = _on_disk_workflows(root)
    repointed: list[dict] = []

    for wf in plan.get("workflows") or []:
        if not isinstance(wf, dict) or not wf.get("name"):
            continue
        name = str(wf["name"])
        trigger = wf.get("trigger")
        trigger_str = (
            trigger if isinstance(trigger, str)
            else str((trigger or {}).get("type") or "") if isinstance(trigger, dict)
            else ""
        ).strip()
        if not trigger_str.lower().startswith("form"):
            continue
        dispatch_name = disk.get(_canon(name))
        if dispatch_name is None:
            continue  # no on-disk definition — nothing safe to point at

        m = re.search(r"\bon\s+(.+)$", trigger_str, re.IGNORECASE)
        candidates = re.split(r"\s+or\s+|,", m.group(1), flags=re.IGNORECASE) \
            if m else []
        route = None
        for cand in candidates:
            cand = cand.strip().split()[0] if cand.strip() else ""
            if cand and (route := _resolve_page_route(cand, plan)) is not None:
                break
        if route is None:
            continue
        path = _schema_path_for_route(root, route)
        doc = _load_doc(path) if path else None
        if not doc:
            continue

        changed = False
        for node in _walk(doc):
            if _node_type(node) != "Form":
                continue
            props = node.get("props")
            if not isinstance(props, dict):
                continue
            ref = props.get("workflow")
            if not isinstance(ref, str) or not ref:
                continue
            if _canon(ref) in disk:
                continue  # live ref — leave it alone
            props["workflow"] = dispatch_name
            changed = True
            repointed.append({"route": route, "dead_ref": ref,
                              "workflow": dispatch_name})
        if changed and path is not None:
            _write_doc(path, doc)
            logger.info("[materializer] repointed dead form ref on %s → %s",
                        route, dispatch_name)
    return {"repointed": repointed}


# ══════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════

def run(output_dir: str | Path) -> dict:
    """All repairs. Never raises — a failed repair leaves the gate
    error standing, which is the correct degraded behaviour."""
    try:
        transitions = materialize_transitions(output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[materializer] transitions pass failed: %s", exc)
        transitions = {"injected": [], "skipped": [], "error": str(exc)}
    try:
        launchers = materialize_workflow_launchers(output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[materializer] launchers pass failed: %s", exc)
        launchers = {"injected": [], "skipped": [], "error": str(exc)}
    try:
        form_refs = repoint_dead_form_refs(output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[materializer] form-ref pass failed: %s", exc)
        form_refs = {"repointed": [], "error": str(exc)}
    return {"transitions": transitions, "workflow_launchers": launchers,
            "form_refs": form_refs}


__all__ = [
    "materialize_transitions",
    "materialize_workflow_launchers",
    "repoint_dead_form_refs",
    "run",
]
