"""Page-anatomy contracts — the UX floor per page kind (item 5).

The widget-anatomy work proved the pattern for dashboards (KPI/chart
recipes); this extends it to the page kinds the reference-app audit
found structurally present but missing their interaction furniture:

  - **detail** pages: a back affordance — ALWAYS, not only when a
    nav-flow transition happens to declare one (that case is the
    transition materializer's). A detail page without a way back is a
    dead end on mobile where browser chrome is hidden.
  - **list** pages: a create affordance — when a create route for the
    page's entity exists in the registry but no button on the list
    navigates to it, the feature exists and is unreachable from where
    users look for it.
  - **search** pages: an explicit no-match state on the results
    container — a silently empty results area after a query reads as
    broken, not as "no results".
  - **detail** primary action (report-only): a detail page whose only
    button is Back has no action at all — flagged as info, never
    repaired, because inventing a domain action is planner/LLM
    judgment, not a guard's.

Which slots already have owners (and are therefore NOT here):
row-click → table_row_nav_guard; create ROUTES → ensure_create_routes;
list/dashboard empty-state copy → empty-state library + FIX-4;
loading skeletons → SKEL-1 contract.

All repairs are additive + idempotent, same button shapes the
materializer uses. Report: contracts/page-anatomy.json. Wired in
post_generate_fixes after density frames, before the materializer.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from services.binding_validator import _read_schema_tables, _SlugResolver
from services.delivery_gate import (
    _BUTTON_TYPES,
    _load_registry_routes,
    _node_label,
    _node_type,
    _norm_route,
    _walk,
)
from services.route_dedup import page_signature
from services.route_tree import build_route_tree
from services.dashboard_anatomy import (
    dashboard_findings,
    is_dashboard_route,
)
from services.transition_materializer import _humanize

logger = logging.getLogger(__name__)

_BACKISH = ("back", "cancel", "return", "close")
_CREATE_SUFFIXES = ("/new", "/upload", "/create")
_RESULT_TYPES = {"Table", "List", "CardGrid", "Repeat"}


# ── shared helpers ──────────────────────────────────────────────────

def _nav_targets(doc: dict) -> set[str]:
    """Every route a node on this page navigates to."""
    out: set[str] = set()
    for n in _walk(doc):
        holders = [n]
        if isinstance(n.get("props"), dict):
            holders.append(n["props"])
        for h in holders:
            for key in ("navigate", "href", "rowHref"):
                v = h.get(key)
                if isinstance(v, str) and v.startswith("/"):
                    out.add(_norm_route(v.split("?")[0]))
            oc = h.get("onClick")
            if isinstance(oc, dict) and isinstance(oc.get("target"), str):
                out.add(_norm_route(oc["target"].split("?")[0]))
    return out


def _has_backish_button(doc: dict) -> bool:
    return any(
        _node_type(n) in _BUTTON_TYPES
        and _node_label(n).lower() in _BACKISH
        for n in _walk(doc)
    )


def _button_count(doc: dict) -> int:
    return sum(1 for n in _walk(doc) if _node_type(n) in _BUTTON_TYPES)


def _container(doc: dict) -> list | None:
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


# ── per-slot rules ──────────────────────────────────────────────────

def _fix_detail_back(route: str, doc: dict, parent: str | None) -> dict | None:
    """Detail/edit page without a back-ish button → inject one to the
    parent route.

    ``parent`` comes from the route tree and is therefore guaranteed to
    be a route that EXISTS — it is the nearest real ancestor, not
    ``route.rsplit("/", 1)[0]``. That distinction is the whole repair:
    a page at ``/products/[id]/edit`` in an app with no
    ``/products/[id]`` route used to report "parent not in registry"
    and inject nothing, while ``/products`` sat there linkable.
    """
    if _has_backish_button(doc):
        return None
    if not parent:
        return {"slot": "detail_back", "route": route, "action": "reported",
                "detail": "no back affordance and no reachable ancestor route"}
    container = _container(doc)
    if container is None:
        return {"slot": "detail_back", "route": route, "action": "reported",
                "detail": "no injectable container"}
    container.insert(0, {
        "id": f"anat_back_{_norm_route(route).strip('/').replace('/', '_')}",
        "type": "Button",
        "props": {"label": "Back", "variant": "outline",
                  "onClick": {"action": "navigate", "target": parent}},
    })
    return {"slot": "detail_back", "route": route, "action": "injected",
            "target": parent}


def _fix_list_create(route: str, doc: dict, entity: str,
                     registry: set[str]) -> dict | None:
    """List page whose entity has a live create route but no button
    pointing at it → inject the affordance at the top of the page."""
    base = _norm_route(route)
    candidates = [base + s for s in _CREATE_SUFFIXES]
    create_route = next((c for c in candidates if c in registry), None)
    if create_route is None:
        return None  # nothing to link — ensure_create_routes' territory
    if create_route in _nav_targets(doc):
        return None  # affordance exists
    container = _container(doc)
    if container is None:
        return {"slot": "list_create", "route": route, "action": "reported",
                "detail": "create route exists but page has no injectable container"}
    label = f"New {_humanize(entity).rstrip('s') or 'Item'}" \
        if not create_route.endswith("/upload") else "Upload"
    container.insert(0, {
        "id": f"anat_create_{_norm_route(route).strip('/').replace('/', '_') or 'index'}",
        "type": "Button",
        "props": {"label": label, "variant": "primary",
                  "onClick": {"action": "navigate", "target": create_route}},
    })
    return {"slot": "list_create", "route": route, "action": "injected",
            "target": create_route}


def _fix_search_states(route: str, doc: dict) -> dict | None:
    """Results container on a search page must declare a no-match
    state. Backfill emptyText where absent."""
    fixed = 0
    for n in _walk(doc):
        if _node_type(n) not in _RESULT_TYPES:
            continue
        props = n.setdefault("props", {})
        if not isinstance(props, dict):
            continue
        if not (isinstance(props.get("emptyText"), str) and props["emptyText"].strip()):
            props["emptyText"] = "No results match your search."
            fixed += 1
    if not fixed:
        return None
    return {"slot": "search_no_match", "route": route, "action": "injected",
            "containers": fixed}


def _check_detail_primary_action(route: str, doc: dict) -> dict | None:
    """Report-only: a detail page whose only button is Back has no
    action a user can take on the record. Inventing one is planner
    judgment — surface, don't repair."""
    buttons = _button_count(doc)
    backish = 1 if _has_backish_button(doc) else 0
    if buttons - backish > 0:
        return None
    return {"slot": "detail_primary_action", "route": route,
            "action": "reported", "severity": "info",
            "detail": "detail page has no action beyond navigation — "
                      "consider a primary action (edit / domain verb)"}


# ── routes this JSON pass cannot patch ──────────────────────────────

_TSX_BACK_HINTS = ("router.back(", "useRouter", 'href="/', "Back",
                   "ArrowLeft", "ChevronLeft", "breadcrumb", "Breadcrumb")


def _audit_unpatchable_details(root: Path, tree) -> list[dict]:
    """Report detail routes that ship as hand-written .tsx.

    920 of the corpus's 921 detail routes have no page schema — they are
    template-injected .tsx or served by the [...slug] catch-all. We
    cannot inject a JSON node into those from here, but letting them
    fall out of the contract entirely is how the dead-end rule came to
    fire on one page in nine hundred.

    Read the file before complaining: several templates already ship a
    back affordance in JSX (tasks/[id] imports useRouter), and reporting
    those would be a false positive.
    """
    out: list[dict] = []
    for route in tree.detail_routes():
        node = tree.nodes[route]
        if node.schema_name:
            continue                      # pass 1 already handled it
        text = ""
        if node.page_path:
            try:
                text = (root / node.page_path).read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                text = ""
        if text and any(h in text for h in _TSX_BACK_HINTS):
            continue                      # already navigable
        out.append({
            "slot": "detail_back", "route": route, "action": "reported",
            "severity": "warn",
            "detail": (f"detail route has no page schema to patch"
                       f"{' and no back affordance in its .tsx' if text else ''}"
                       f"; reachable parent: {node.parent or 'none'}"),
            "parent": node.parent,
            "page_path": node.page_path,
        })
    return out


# ── the pass ────────────────────────────────────────────────────────

def apply_page_anatomy(output_dir: str | Path) -> dict:
    """Enforce the per-kind UX floor. Returns the report dict."""
    root = Path(output_dir)
    sdir = root / "src" / "schemas"
    findings: list[dict] = []
    if not sdir.is_dir():
        return {"findings": findings}

    registry = {_norm_route(r) for r in _load_registry_routes(root)}
    # The resource registry — column types, enums, FK targets — is what makes
    # "this chart groups by a UUID" decidable rather than a guess.
    try:
        _registry = json.loads(
            (root / "contracts" / "resource-registry.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        _registry = {}
    resolver = _SlugResolver(_read_schema_tables(str(root)))
    # The route tree — not this directory — is the authority on which
    # pages exist and how deep the app is. src/schemas is flat (1 of
    # 1440 page schemas across the corpus is a dynamic route); src/app
    # holds 921 real detail routes.
    tree = build_route_tree(root)
    # _norm_route collapses "[id]" → "{id}"; the tree keys on the raw
    # Next.js form. Index both ways or every detail route misses.
    tree_by_norm = {_norm_route(r): n for r, n in tree.nodes.items()}

    for p in sorted(sdir.rglob("*.json")):
        if p.name == "shell.json":
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("root"), dict):
            continue
        rel = p.relative_to(sdir).with_suffix("")
        route = doc.get("route") if isinstance(doc.get("route"), str) else \
            ("/" + "/".join(rel.parts) if str(rel) != "index" else "/")

        node = tree_by_norm.get(_norm_route(route))

        # Dashboards first, and deliberately BEFORE the signature read.
        # page_signature names a job only when it can attribute the page to an
        # entity; a dashboard belongs to none, so it returned None and every
        # dashboard fell through the `continue` below — never judged at all.
        if is_dashboard_route(route):
            dash = dashboard_findings(route, doc, _registry)
            findings.extend(dash)
            continue

        sig = page_signature(route, doc, resolver)
        if sig is not None:
            entity, job = sig
        elif node is not None and node.kind in ("detail", "edit", "list", "sub"):
            # The signature reader could not name an entity, but the ROUTE
            # says what this page is. Route shape beats content inference.
            entity, job = "", ("list" if node.kind == "sub" else node.kind)
        else:
            continue

        page_findings: list[dict] = []
        if job in ("detail", "edit"):
            for f in (_fix_detail_back(route, doc, node.parent if node else None),
                      _check_detail_primary_action(route, doc)):
                if f:
                    page_findings.append(f)
        elif job == "list":
            f = _fix_list_create(route, doc, entity, registry)
            if f:
                page_findings.append(f)
        elif job == "search":
            f = _fix_search_states(route, doc)
            if f:
                page_findings.append(f)

        if any(f["action"] == "injected" for f in page_findings):
            try:
                p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[anatomy] could not write %s: %s", p, exc)
        findings.extend(page_findings)

    findings.extend(_audit_unpatchable_details(root, tree))

    injected = [f for f in findings if f["action"] == "injected"]
    if injected:
        logger.info("[anatomy] repaired %d slot(s): %s", len(injected),
                    ", ".join(f"{f['route']}:{f['slot']}" for f in injected[:6]))
    report = {"findings": findings,
              "summary": {"injected": len(injected),
                          "reported": len(findings) - len(injected),
                          # Actionable = reported AND not merely informational
                          # ("consider a primary action" is a suggestion, not a
                          # defect) — the scorecard penalizes ONLY these.
                          "reported_actionable": sum(
                              1 for f in findings
                              if f.get("action") == "reported"
                              and f.get("severity") != "info")}}
    try:
        out = root / "contracts" / "page-anatomy.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return report


__all__ = ["apply_page_anatomy"]
