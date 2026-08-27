"""Route dedup — one user job, one route (F3 / item 4).

The reference-app audit found the redundancy class: multiple emitters
each do their job correctly and the app ends up with two routes serving
the same user job — ``/`` (upload form) vs ``/documents/upload``,
phantom ``/documents/new`` next to an upload page, two search screens.
Each route is individually valid, so no per-route guard can see the
problem; it only exists at the *set* level.

Rule enforced here: **every route must have exactly one reason to
exist, and every reason must have exactly one route.** A page's reason
is its job signature — ``(entity, job)`` where job ∈ create / list /
detail / edit / search / dashboard, derived structurally from the
schema (never from names alone).

When two concrete routes share a signature:
  - a WINNER is chosen (plan-declared beats not; then most inbound
    references — nav menu, transitions, navigate props; ``/`` gets a
    landing bonus so the home page never bounces; then shortest route),
  - every LOSER's schema is rewritten to a ``Redirect`` node pointing
    at the winner. The route stays registered — deep links, nav
    targets, and the delivery gate's planned-page check all remain
    satisfied — but users always land on the canonical page,
  - navigate targets and shell-menu links across all schemas are
    repointed to the winner so most users never even touch the alias.

Deliberately NOT collapsed: pages whose job can't be derived (job None
— ambiguity means keep both), param-route groups with different param
semantics (same signature = same entity+job, so they do collapse), and
anything already a Redirect (idempotency).

Runs in post_generate_fixes BEFORE the transition materializer, so
button injection and the delivery gate operate on the canonical route
set. Report: contracts/route-dedup.json.
"""
from __future__ import annotations

import json
import re
import logging
from pathlib import Path

from services.binding_validator import _read_schema_tables, _SlugResolver
from services.delivery_gate import (
    _canon,
    _load_nav_flow,
    _load_page_schemas,
    _load_plan,
    _node_type,
    _norm_route,
    _walk,
)

logger = logging.getLogger(__name__)

_DASH_TYPES = {"MetricTile", "Chart", "Stat", "Gauge", "SplitArc", "Heatmap"}
_LIST_TYPES = {"Table", "List", "Kanban", "Calendar", "CardGrid", "Repeat"}


# ══════════════════════════════════════════════════════════════════
# Job signatures
# ══════════════════════════════════════════════════════════════════

def _form_entity(page: dict, resolver: _SlugResolver) -> str | None:
    for n in _walk(page):
        if _node_type(n) == "Form":
            props = n.get("props") if isinstance(n.get("props"), dict) else {}
            for key in ("entity", "resource", "table"):
                v = props.get(key)
                if isinstance(v, str) and v and resolver.resolve(v):
                    return _canon(resolver.resolve(v))
    return None


def _datasource_entity(page: dict, resolver: _SlugResolver) -> str | None:
    for ds in page.get("dataSources") or []:
        if isinstance(ds, dict):
            for key in ("source", "table", "from", "entity", "name"):
                v = ds.get(key)
                if isinstance(v, str) and v and resolver.resolve(v):
                    return _canon(resolver.resolve(v))
    return None


def _page_entity(route: str, page: dict, resolver: _SlugResolver,
                 job: str | None = None) -> str | None:
    """Primary entity — the page's SUBJECT, canonicalised.

    Which signal is authoritative depends on the job. On a write page
    the dataSources feed the FK dropdowns, not the subject: a Product
    create form loads suppliers + categories to populate its selects,
    so reading dataSources first attributes /products/new to
    "supplier". That misattribution grouped three entities' create
    pages under one signature and collapsed two of them, so "Add
    Product" opened the supplier form (live on 5u9du8jt). For write
    jobs the Form's own resource wins, then the route; dataSources are
    never consulted."""
    if job in ("create", "edit"):
        return _form_entity(page, resolver) or _route_entity(route, resolver)
    return (_datasource_entity(page, resolver)
            or _form_entity(page, resolver)
            or _route_entity(route, resolver))


def _route_entity(route: str, resolver: _SlugResolver) -> str | None:
    seg = _norm_route(route).lstrip("/").split("/", 1)[0]
    if seg and resolver.resolve(seg):
        return _canon(resolver.resolve(seg))
    return None


def _page_job(route: str, page: dict) -> str | None:
    """Structural job classification. Order matters: param routes are
    detail/edit regardless of content; search beats create (a search
    page contains an input too)."""
    types = {_node_type(n) for n in _walk(page)}
    if "Redirect" in types:
        return None  # already an alias — never re-collapse
    norm = _norm_route(route)
    if "{" in norm:
        return "edit" if norm.endswith("/edit") else "detail"
    if "search" in norm.lower() or "SearchInput" in types:
        return "search"
    if "Form" in types:
        return "create"
    if types & _DASH_TYPES:
        return "dashboard"
    if types & _LIST_TYPES:
        return "list"
    return None


def page_signature(route: str, page: dict, resolver: _SlugResolver) -> tuple[str, str] | None:
    job = _page_job(route, page)
    if job is None:
        return None
    entity = _page_entity(route, page, resolver, job)
    if entity is None:
        return None
    return (entity, job)


# ══════════════════════════════════════════════════════════════════
# Winner selection
# ══════════════════════════════════════════════════════════════════

def _inbound_refs(route: str, schemas: list[tuple[str, dict]],
                  nav_flow: dict, shell: dict) -> int:
    """How much of the app points at this route already."""
    norm = _norm_route(route)
    n = 0
    blob_targets: list[str] = []
    for _r, doc in schemas:
        for node in _walk(doc):
            props = node.get("props") if isinstance(node.get("props"), dict) else {}
            for key in ("navigate", "href", "rowHref"):
                v = props.get(key) or node.get(key)
                if isinstance(v, str):
                    blob_targets.append(v)
            oc = props.get("onClick")
            if isinstance(oc, dict) and isinstance(oc.get("target"), str):
                blob_targets.append(oc["target"])
    for t in blob_targets:
        if _norm_route(t.split("?")[0]) == norm:
            n += 1
    route_by_id = {str(p.get("id")): _norm_route(str(p.get("route") or ""))
                   for p in (nav_flow.get("pages") or []) if isinstance(p, dict)}
    for t in nav_flow.get("transitions") or []:
        if isinstance(t, dict) and route_by_id.get(str(t.get("to"))) == norm:
            n += 1
    for item in _walk(shell):
        for key in ("href", "navigate", "route"):
            v = item.get(key)
            if isinstance(v, str) and _norm_route(v) == norm:
                n += 1
    return n


def _pick_winner(routes: list[str], plan_routes: set[str],
                 schemas: list[tuple[str, dict]], nav_flow: dict,
                 shell: dict) -> str:
    def score(r: str) -> tuple:
        norm = _norm_route(r)
        return (
            2 if norm == "/" else 0,        # landing never bounces
            2 if norm in plan_routes else 0,  # the plan's word counts
            _inbound_refs(r, schemas, nav_flow, shell),
            -len(norm),                       # shorter = more canonical
        )
    return max(sorted(routes), key=score)


# ══════════════════════════════════════════════════════════════════
# The pass
# ══════════════════════════════════════════════════════════════════

def _schema_path(root: Path, route: str) -> Path | None:
    sdir = root / "src" / "schemas"
    norm = _norm_route(route)
    if norm == "/":
        p = sdir / "index.json"
        return p if p.is_file() else None
    for candidate in (norm, norm.replace("{", "[").replace("}", "]")):
        p = sdir / (candidate.lstrip("/") + ".json")
        if p.is_file():
            return p
    return None


def _repoint_targets(root: Path, loser: str, winner: str) -> int:
    """Rewrite navigate/href/menu targets loser→winner across schemas +
    shell.json. String-equality on normalized route; bindings untouched."""
    changed = 0
    loser_n = _norm_route(loser)

    def _fix(node: dict) -> int:
        c = 0
        for holder in (node, node.get("props") if isinstance(node.get("props"), dict) else {}):
            if not isinstance(holder, dict):
                continue
            for key in ("navigate", "href", "rowHref", "route"):
                v = holder.get(key)
                if isinstance(v, str) and _norm_route(v.split("?")[0]) == loser_n:
                    holder[key] = winner
                    c += 1
            oc = holder.get("onClick")
            if isinstance(oc, dict) and isinstance(oc.get("target"), str) \
                    and _norm_route(oc["target"].split("?")[0]) == loser_n:
                oc["target"] = winner
                c += 1
        return c

    for p in sorted((root / "src" / "schemas").rglob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        # The document dict itself is excluded: its top-level "route" is
        # the page's IDENTITY, not a navigation target — rewriting it
        # would corrupt the alias we just wrote.
        c = sum(_fix(n) for n in _walk(doc)
                if isinstance(n, dict) and n is not doc)
        if c:
            p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            changed += c
    return changed


def dedupe_routes(output_dir: str | Path) -> dict:
    """Run the pass. Returns {collapsed: [...], groups: n}."""
    root = Path(output_dir)
    schemas = _load_page_schemas(root)
    resolver = _SlugResolver(_read_schema_tables(str(root)))
    plan = _load_plan(root)
    nav_flow = _load_nav_flow(root)
    try:
        shell = json.loads((root / "src" / "schemas" / "shell.json").read_text())
    except Exception:  # noqa: BLE001
        shell = {}
    plan_routes = {
        _norm_route(str(p.get("route")))
        for p in (plan.get("pages") or [])
        if isinstance(p, dict) and p.get("route")
    }

    groups: dict[tuple[str, str], list[str]] = {}
    page_by_route = {_norm_route(r): (r, doc) for r, doc in schemas}
    for r, doc in schemas:
        sig = page_signature(r, doc, resolver)
        if sig is not None:
            groups.setdefault(sig, []).append(r)

    collapsed: list[dict] = []
    kept_conflicts: list[dict] = []
    for sig, routes in sorted(groups.items()):
        uniq = sorted({_norm_route(r) for r in routes})
        if len(uniq) < 2:
            continue
        # PLAN AUTHORITY. This pass exists to delete routes no one asked
        # for — the phantom twins several emitters each invent. A route
        # someone deliberately asked for is a product decision, and a
        # structural signature is far too coarse to overrule it:
        # /admins, /staffs and /viewers are all (users, list) yet are
        # three deliberate persona views, and collapsing them replaced
        # two with Redirects so every persona showed the same screen
        # (live on 5u9du8jt). Deliberate = declared in the plan, or "/"
        # (the front door is never a bounce). When a whole group is
        # deliberate we report the conflict instead of resolving it —
        # genuine redundancy between two planned pages is the planner's
        # to fix, not something a post-gen pass may silently delete.
        protected = {r for r in uniq if r in plan_routes or r == "/"}
        collapsible = [r for r in uniq if r not in protected]
        if not collapsible:
            if len(protected) > 1:
                kept_conflicts.append({"entity": sig[0], "job": sig[1],
                                       "routes": sorted(protected)})
                logger.info("[route-dedup] kept %d deliberate peers for %s/%s",
                            len(protected), sig[0], sig[1])
            continue
        winner = _pick_winner(sorted(protected) or uniq, plan_routes,
                              schemas, nav_flow, shell)
        for loser in collapsible:
            if loser == winner:
                continue
            orig_route, _doc = page_by_route[loser]
            path = _schema_path(root, orig_route)
            if path is None:
                continue
            alias = {
                "route": orig_route,
                "root": {
                    "type": "Stack",
                    "children": [{
                        "id": f"dedup_{_canon(loser)}",
                        "type": "Redirect",
                        "props": {"to": winner},
                    }],
                },
            }
            try:
                path.write_text(json.dumps(alias, indent=2), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[route-dedup] could not write alias %s: %s",
                               path, exc)
                continue
            repointed = _repoint_targets(root, loser, winner)
            collapsed.append({
                "entity": sig[0], "job": sig[1],
                "loser": loser, "winner": winner,
                "repointed_refs": repointed,
            })
            logger.info("[route-dedup] %s ⇒ %s (%s/%s, %d refs repointed)",
                        loser, winner, sig[0], sig[1], repointed)

    report = {"groups": len(groups), "collapsed": collapsed,
              "kept_conflicts": kept_conflicts}
    try:
        out = root / "contracts" / "route-dedup.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return report


# ══════════════════════════════════════════════════════════════════
# API-endpoint dedup (DEDUP-2)
# ══════════════════════════════════════════════════════════════════

def dedupe_search_endpoints(output_dir: str | Path) -> dict:
    """One search path per app.

    The injected ``/api/search`` route is the single search authority
    (tsvector-backed, tested). An LLM-authored sibling like
    ``/api/documents/search`` survives api_route_prune because its
    parent segment ("documents") is reserved for injected infra — this
    is exactly how the reference app shipped two search endpoints, one
    of which 500'd. Any nested ``**/search/route.ts`` that isn't the
    canonical one is a second authority and gets deleted; page schemas
    fetch ``/api/search`` and are unaffected.
    """
    root = Path(output_dir)
    api = root / "src" / "app" / "api"
    removed: list[str] = []
    if api.is_dir():
        canonical = api / "search" / "route.ts"
        for p in sorted(api.rglob("search/route.ts")):
            if p == canonical:
                continue
            try:
                p.unlink()
                # Prune now-empty parents up to api/ so Next doesn't see
                # dangling empty segments.
                d = p.parent
                while d != api and not any(d.iterdir()):
                    d.rmdir()
                    d = d.parent
                removed.append(str(p.relative_to(root)))
                logger.info("[route-dedup] removed duplicate search endpoint %s", p)
            except OSError as exc:
                logger.warning("[route-dedup] could not remove %s: %s", p, exc)
    return {"removed": removed}


__all__ = ["dedupe_routes", "dedupe_schema_files", "dedupe_search_endpoints", "page_signature"]

# ─────────────────────────────────────────────────────────────────────
# Schema-FILE dedup — two files declaring the same route
# ─────────────────────────────────────────────────────────────────────

_REGISTRY_IMPORT_RE = re.compile(
    r'"(?P<route>/[^"]*)"\s*:\s*\(\)\s*=>\s*import\("\./(?P<path>[^"]+\.json)"\)')


def _registry_file_map(root: Path) -> dict[str, str]:
    """route → schema file path, from src/schemas/registry.ts — the ONLY
    authority on which file actually serves a route at runtime."""
    reg = root / "src" / "schemas" / "registry.ts"
    if not reg.is_file():
        return {}
    try:
        text = reg.read_text(encoding="utf-8")
    except OSError:
        return {}
    return {m.group("route"): m.group("path")
            for m in _REGISTRY_IMPORT_RE.finditer(text)}


def dedupe_schema_files(output_dir: str | Path) -> dict:
    """Remove schema files shadowed by another file declaring the SAME
    route (index.json vs home.json for "/", flattened vs nested names).

    Winner selection: the file registry.ts imports for that route; when
    the registry is silent, the deeper (nested) path — that is the layout
    every registry writer emits. Losers can never resolve at runtime
    (the proof pass flags them as duplicate-route), so deleting them is
    strictly safe. Idempotent.
    """
    root = Path(output_dir)
    sdir = root / "src" / "schemas"
    removed: list[dict] = []
    if not sdir.is_dir():
        return {"removed": removed}
    by_route: dict[str, list[Path]] = {}
    for p in sorted(sdir.rglob("*.json")):
        if p.name == "shell.json":
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        route = doc.get("route") if isinstance(doc, dict) else None
        if isinstance(route, str) and route.strip():
            norm = "/" + route.strip().strip("/")
            if route.strip() == "/":
                norm = "/"
            by_route.setdefault(norm, []).append(p)
    reg_map = _registry_file_map(root)
    for route, files in by_route.items():
        if len(files) < 2:
            continue
        reg_rel = reg_map.get(route)
        winner = None
        if reg_rel:
            for f in files:
                if str(f.relative_to(sdir)) == reg_rel:
                    winner = f
                    break
        if winner is None:
            # Deeper path wins (nested layout is the registry convention).
            winner = max(files, key=lambda f: (len(f.relative_to(sdir).parts),
                                               f.name != "index.json"))
        for f in files:
            if f == winner:
                continue
            try:
                f.unlink()
                removed.append({"route": route,
                                "removed": str(f.relative_to(sdir)),
                                "kept": str(winner.relative_to(sdir))})
                logger.info("[schema-dedup] %s: removed %s (kept %s)",
                            route, f.name, winner.name)
            except OSError as e:
                logger.warning("[schema-dedup] could not remove %s: %s", f, e)
    return {"removed": removed}
