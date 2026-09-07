"""Deterministic backfill for empty/stub page schemas.

## Part-1 root cause (why this guard exists)
`run_page_schema_agent`'s last-resort floor `_minimal_schema(slug, page_type)` ships a
structurally-VALID but content-empty page — `Stack → Heading(page_type.capitalize())`,
`dataSources: []`, zero widgets — whenever the single-call LLM path overflows/errors across
every retry AND the chunked (skeleton+region) path also fails to produce a valid schema.
That stub passes `_validate_schema_json` (root is a Stack whose first child is a Heading)
and therefore passes every downstream gate, so it SHIPS. Worse: because a stub FILE now
exists on disk, `check_pages_coverage` / `fill_missing_pages` / `_fill_missing_with_stubs`
all treat the route as "covered" and never regenerate it — the stub is terminal. That is
exactly how `output/afwn8nya` shipped `home.json` / `analytics.json` / `interviews.json` as
308-324 byte `Stack+Heading("Dashboard")` shells while the entity pages came out full.

## What this does
The safety net: detect a stub page for a route the app SHOULD populate (home/dashboard, an
entity list, a report/analytics page) and fill it deterministically from the REAL registered
entity slugs (read via the same `binding_validator` reader the binding gate uses), so it
renders real data AND passes the binding validator. Idempotent — a page that already has real
content (a Table/Chart/MetricTile/Form or any dataSource/binding) is left untouched. Never
raises: any failure degrades to leaving the page as-is.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# Node types that mean a page already renders real content — if any appears, the page
# is NOT a stub. (Kept in canon form: lower, alnum-only.)
_CONTENT_TYPES = {
    "table", "datagrid", "datatable", "datalist", "list", "cardlist", "repeat",
    "chart", "metrictile", "stat", "statgroup", "form", "gauge", "heatmap",
    "resourcetimeline", "descriptionlist", "kanban", "calendar", "schematic",
    "stepper", "timeline", "activityfeed", "approvalstepper", "funnel",
}

# Entities that are infrastructure, not domain data — never featured on a dashboard.
_SYSTEM_ENTITIES = {
    "users", "user", "session", "sessions", "account", "accounts", "auth",
    "auditlog", "auditlogs", "forgefiles", "forgenotifications", "forgeschedules",
    "notification", "notifications", "file", "files",
}

_ANALYTICS_TOKENS = ("analytics", "report", "reports", "overview", "insights",
                     "metrics", "summary", "dashboard")


def _canon(s) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower()) if isinstance(s, str) else ""


# ── stub detection ────────────────────────────────────────────────────────────

def _iter_nodes(node):
    """Yield every dict node in a schema subtree."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            if isinstance(v, list):
                for item in v:
                    yield from _iter_nodes(item)
            elif isinstance(v, dict):
                yield from _iter_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)


def _has_binding(obj) -> bool:
    """True if any string anywhere in the subtree carries a `{{...}}` binding."""
    if isinstance(obj, str):
        return "{{" in obj
    if isinstance(obj, dict):
        return any(_has_binding(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_binding(v) for v in obj)
    return False


def is_stub_page(page: dict) -> bool:
    """A page is a stub when it renders essentially nothing: no dataSources, no
    content-bearing node (Table/Chart/MetricTile/Form/List/...), and no `{{binding}}`
    anywhere. A single Heading (± a Text/Stack) is a stub; anything with real content
    is not."""
    if not isinstance(page, dict):
        return False
    ds = page.get("dataSources")
    if isinstance(ds, list) and ds:
        return False
    root = page.get("root")
    if not isinstance(root, dict):
        return False
    for node in _iter_nodes(root):
        if _canon(node.get("type")) in _CONTENT_TYPES:
            return False
    if _has_binding(root):
        return False
    return True


# ── deterministic builders ─────────────────────────────────────────────────────

def _pluralize(name: str) -> str:
    """Deprecated. New callers should use ``derive_names(entity).label``
    directly. Kept as a thin wrapper for the two existing call-sites
    that pass an already-humanized entity name (``'Assessment Day'``)
    and expect the humanized plural (``'Assessment Days'``)."""
    if not name:
        return name
    # Strip humanization → PascalCase → canonical label.
    from services.entity_names import derive_names
    entity_pascal = "".join(w for w in name.split() if w)
    return derive_names(entity_pascal).label


def _metric_tile(entity: str, slug: str) -> tuple[dict, dict]:
    """(aggregate dataSource, MetricTile node) — a live count for one entity."""
    from services.deterministic_pages import _humanize_entity
    ds = {
        "name": f"{slug}Stats",
        "op": "aggregate",
        "entity": entity,
        "metrics": {"count": {"fn": "count", "entity": entity}},
    }
    tile = {
        "type": "MetricTile",
        "props": {
            "label": f"Total {_pluralize(_humanize_entity(entity))}",
            "value": f"{{{{{slug}Stats.count}}}}",
            "hint": f"All {_humanize_entity(entity).lower()} records",
        },
    }
    return ds, tile


def _recent_section(entity: str, slug: str, fields: dict, has_detail: bool = False) -> tuple[dict, dict]:
    """(list dataSource, section node) — a "Recent <Entity>" table for one entity.

    A rowHref is emitted only when the data entity has a real `/slug/[id]` detail
    route (`has_detail`) — the dashboard isn't covered by table_row_nav_guard, so an
    unconditional rowHref here would route row clicks to a 404. The slug is the DATA
    entity's own slug, never the dashboard page slug.
    """
    from services.deterministic_pages import _display_columns, _label, _humanize_entity
    ds = {"name": f"{slug}Recent", "op": "list", "entity": entity, "limit": 5}
    cols = [{"key": c, "label": _label(c)} for c in _display_columns(fields, limit=5)]
    table_props: dict = {"columns": cols, "rows": f"{{{{{slug}Recent}}}}"}
    if has_detail:
        table_props["rowHref"] = f"/{slug}/{{id}}"
    section = {
        "type": "Stack",
        "props": {"gap": "tokens.spacing.4"},
        "children": [
            {"type": "Heading",
             "props": {"content": f"Recent {_pluralize(_humanize_entity(entity))}", "level": 2}},
            {"type": "Table", "props": table_props},
        ],
    }
    return ds, section


def _build_dashboard(title: str, primaries: list[tuple[str, str, dict]],
                     detail_slugs: set[str] | None = None) -> dict:
    """A domain-shaped dashboard: one live count tile per primary entity + a
    "Recent <Entity>" table for the top 1-2 entities. `primaries` = [(entity, slug, fields)].
    `detail_slugs` = canon slugs that HAVE a `/slug/[id]` detail route; a recent
    table only deep-links when its entity is in that set (else a 404 on row click)."""
    detail_slugs = detail_slugs or set()
    data_sources: list[dict] = []
    tiles: list[dict] = []
    for entity, slug, _fields in primaries:
        ds, tile = _metric_tile(entity, slug)
        data_sources.append(ds)
        tiles.append(tile)

    children: list[dict] = [
        {"type": "Heading", "props": {"content": title, "level": 1}},
    ]
    if tiles:
        children.append({
            "type": "Grid",
            "props": {"columns": min(4, len(tiles)) or 1, "gap": "tokens.spacing.4"},
            "children": tiles,
        })
    for entity, slug, fields in primaries[:2]:
        ds, section = _recent_section(entity, slug, fields, _canon(slug) in detail_slugs)
        data_sources.append(ds)
        children.append(section)

    return {
        "dataSources": data_sources,
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.semantic.section"},
                 "children": children},
    }


def _build_list(entity: str, slug: str, fields: dict, route: str) -> dict:
    """Reuse the standard deterministic list page, then pin its dataSource name + rows
    binding to the REAL registered slug so the binding gate resolves them."""
    from services.deterministic_pages import build_list_page
    page = build_list_page(entity, fields, route, None)
    # build_list_page derives the dataSource name from the route segment; repoint it to
    # the canonical registered slug so the source resolves and the rows binding matches.
    old_names: set[str] = set()
    for ds in page.get("dataSources") or []:
        if isinstance(ds, dict) and ds.get("op") == "list":
            if isinstance(ds.get("name"), str) and ds["name"] != slug:
                old_names.add(ds["name"])
            ds["name"] = slug
            ds["entity"] = entity
    if old_names:
        for node in _iter_nodes(page.get("root")):
            props = node.get("props")
            if not isinstance(props, dict):
                continue
            for key in ("rows", "items", "data"):
                val = props.get(key)
                if isinstance(val, str) and val.strip().strip("{} ") in old_names:
                    props[key] = f"{{{{{slug}}}}}"
    return {"dataSources": page.get("dataSources") or [], "root": page.get("root")}


# ── intent ──────────────────────────────────────────────────────────────────────

def _existing_heading(page: dict) -> str | None:
    for node in _iter_nodes(page.get("root")):
        if _canon(node.get("type")) == "heading":
            content = (node.get("props") or {}).get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return None


def _humanize_slug(slug: str) -> str:
    s = re.sub(r"[-_]+", " ", slug or "").strip()
    return s[:1].upper() + s[1:] if s else "Page"


# ── entry point ───────────────────────────────────────────────────────────────

def backfill_stub_pages(output_dir: str) -> dict:
    """Fill every empty/stub page schema for a route the app should populate, binding
    only to REAL registered entity slugs. Idempotent + never raises.

    Returns {"backfilled": [{route,id,kind}], "skipped": int}.
    """
    result: dict = {"backfilled": [], "skipped": 0}
    try:
        from services.binding_validator import _read_schema_tables, _SlugResolver
        from services.deterministic_pages import resolve_entity

        root = Path(output_dir)
        sdir = root / "src" / "schemas"
        if not sdir.is_dir():
            return result

        resolver = _SlugResolver(_read_schema_tables(output_dir))

        # Canon slugs that have a real `/slug/[id]` detail route — a recent-list
        # rowHref may only deep-link to one of these (the dashboard is not covered
        # by table_row_nav_guard, so an unbacked rowHref would 404 on row click).
        detail_slugs = {_canon(p.parent.name) for p in sdir.glob("*/[[]id[]].json")}

        try:
            registry = json.loads((root / "registry.json").read_text(encoding="utf-8"))
        except Exception:
            registry = {}
        entities = registry.get("entities") if isinstance(registry.get("entities"), dict) else {}

        # Ordered primary (domain) entities that map to a real registered slug.
        primaries: list[tuple[str, str, dict]] = []
        for name, ent in entities.items():
            if not isinstance(name, str) or _canon(name) in _SYSTEM_ENTITIES:
                continue
            if _canon(name).startswith("forge"):
                continue
            slug = resolver.resolve(name)
            if not slug:
                continue
            fields = (ent or {}).get("fields") if isinstance(ent, dict) else {}
            primaries.append((name, slug, fields if isinstance(fields, dict) else {}))

        for path in sorted(sdir.rglob("*.json")):
            try:
                page = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(page, dict) or not is_stub_page(page):
                continue

            route = page.get("route") or ""
            pid = page.get("id") or path.stem
            cr, ci = _canon(route), _canon(pid)

            filled: dict | None = None
            kind = None

            is_dashboard = (
                route == "/" or ci in ("home", "dashboard", "index")
                or "dashboard" in cr
                or any(tok in cr or tok in ci for tok in _ANALYTICS_TOKENS)
            )
            if is_dashboard and primaries:
                title = _existing_heading(page) or _humanize_slug(pid) or "Dashboard"
                if ci in ("home", "index") or route == "/":
                    title = _existing_heading(page) or "Dashboard"
                filled = _build_dashboard(title, primaries, detail_slugs)
                kind = "dashboard"
            else:
                # Single-segment entity list route only (avoid clobbering bespoke
                # sub-pages like /x/calendar or /x/[id]/timeline).
                segs = [s for s in route.split("/") if s]
                if len(segs) == 1:
                    entity = resolve_entity(route, page.get("entity"), entities.keys())
                    slug = resolver.resolve(entity) if entity else None
                    if entity and slug:
                        fields = next((f for e, s, f in primaries if e == entity), None)
                        if fields is None:
                            _e = entities.get(entity) or {}
                            fields = _e.get("fields") if isinstance(_e.get("fields"), dict) else {}
                        filled = _build_list(entity, slug, fields, route)
                        kind = "list"

            if not filled:
                result["skipped"] += 1
                continue

            page["dataSources"] = filled["dataSources"]
            page["root"] = filled["root"]
            page.setdefault("schemaVersion", "2")
            path.write_text(json.dumps(page, indent=2), encoding="utf-8")
            result["backfilled"].append({"route": route, "id": pid, "kind": kind})
            logger.info("stub_page_backfill: filled %s (%s) in %s", pid, kind, output_dir)

    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("stub_page_backfill failed: %s", e)
    return result
