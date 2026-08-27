"""Deterministic sub-dashboard composer.

Owns every dashboard-typed page in ``plan.pages`` **other than** the landing
route (which is composed by :mod:`services.apply_dashboard_maquette`). Reads
each such page's ``widgets`` (and optional ``metrics``) hints from the plan
and emits a schema whose nodes bind to **inline dataSources** — flat
``{op, entity, field}`` shape per widget/tile, no top-level
``op:"aggregate"`` block that could ship without its ``metrics`` map.

Cure for the dz6jba0x ``/mrr-movement`` class: the LLM authored an
``op:"aggregate"`` dataSource named ``mrrSummary`` with NO metrics block,
while bindings ``{{mrrSummary.newMrr}}`` referred to metric keys that
resolved to undefined. Runtime returned ``{}`` → empty tiles. By taking
authorship away from the LLM for these pages and using inline
dataSources instead, the bug class becomes impossible at emit time.

Pure module. Read/writes JSON files but pushes all shape logic through
:func:`services.dashboard_composer.compose_dashboard`. Idempotent: a
second run rewrites byte-identical output. Fail-open per-file — one
broken page never blocks the batch.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.dashboard_composer import compose_dashboard

log = logging.getLogger(__name__)


# Routes owned by ``apply_dashboard_maquette`` — this composer MUST skip
# them so both authorities don't fight over the same file.
_LANDING_ROUTES: frozenset[str] = frozenset({
    "/", "/home", "/dashboard", "/overview", "/admin", "/admin/dashboard",
})


# Plan ``widgets[i].type`` → registered component name. Deliberately small;
# unknown types fall through as-is (compose_dashboard will validate against
# the component registry and swap in a fallback if needed).
_WIDGET_TYPE_TO_COMPONENT: dict[str, str] = {
    "chart": "Chart",
    "table": "Table",
    "list": "List",
    "kanban": "Kanban",
    "calendar": "Calendar",
    "timeline": "Timeline",
    "gauge": "Gauge",
    "heatmap": "Heatmap",
    "metric": "MetricTile",
    "stat": "Stat",
}


# ────────────────────────────────────────────────────────────
# Pure conversion — plan page → compose_dashboard composition
# ────────────────────────────────────────────────────────────

def plan_page_to_composition(page: dict) -> dict:
    """Convert one ``plan.pages[i]`` dict into the ``composition`` shape
    :func:`compose_dashboard` expects.

    Widget rules:
      * ``{type: "chart", entity, title, groupBy, bucket?}`` →
        ``{component: "Chart", bindsTo: entity, ...}``.
      * ``{type: "table", entity, title, limit?, columns?}`` →
        ``{component: "Table", bindsTo: entity, ...}``.
      * Other types map through ``_WIDGET_TYPE_TO_COMPONENT``; unknown
        types pass through so compose_dashboard can validate and
        fall back to Table.

    Tile rules:
      * Emit only when the page explicitly lists ``metrics: [...]``. We
        never infer tiles from prose — that's the LLM's job (which we're
        replacing). The planner must be explicit to get tiles on a
        composer-owned dashboard.
    """
    if not isinstance(page, dict):
        return {"tiles": [], "widgets": []}

    tiles: list[dict] = []
    for m in (page.get("metrics") or []):
        if not isinstance(m, dict):
            continue
        tile = {"kind": "stat"}
        for k in ("label", "entity", "calc", "field", "filter",
                  "numerator", "denominator"):
            if m.get(k) is not None:
                tile[k] = m[k]
        # Default calc when the planner emitted a field without one — sum
        # is the safe reduction for numeric columns.
        if "calc" not in tile and tile.get("field"):
            tile["calc"] = "sum"
        tiles.append(tile)

    widgets: list[dict] = []
    for w in (page.get("widgets") or []):
        if not isinstance(w, dict):
            continue
        w_type = str(w.get("type") or "").strip().lower()
        component = _WIDGET_TYPE_TO_COMPONENT.get(w_type) or w.get("component")
        if not component:
            continue  # can't compose without a component name
        out = {"component": component, "bindsTo": w.get("entity") or w.get("bindsTo")}
        for k in ("title", "groupBy", "colorBy", "sort", "limit", "bucket", "columns"):
            if w.get(k) is not None:
                out[k] = w[k]
        widgets.append(out)

    return {
        "tiles": tiles,
        "widgets": widgets,
        # Reasonable default when tiles exist; compose_dashboard falls
        # back to widgets-only if tiles are empty.
        "layout": "kpi_row_over_two_column_widgets" if tiles else "widgets_only",
    }


# ────────────────────────────────────────────────────────────
# End-to-end — walk plan, compose each sub-dashboard, write to disk
# ────────────────────────────────────────────────────────────

def _route_to_schema_name(route: str) -> str:
    """``/mrr-movement`` → ``mrr-movement.json``; nested routes keep their
    directories (``/reports/mrr`` → ``reports/mrr.json``) — the SAME layout
    registry.ts imports use. Flattening with ``-`` created a SECOND file
    for routes the LLM had already written nested (the fleet's
    duplicate-route class: admin-analytics.json vs admin/analytics.json).
    Empty / root routes are not composed by this pass (returned as empty).
    """
    r = (route or "").strip()
    if not r or r == "/":
        return ""
    return r.strip("/") + ".json"


def _existing_schema_for_route(sdir, route: str):
    """The on-disk schema file that already DECLARES this route, if any —
    composing must overwrite that file, never create a sibling duplicate."""
    norm = "/" + str(route or "").strip("/")
    for p in sorted(sdir.rglob("*.json")):
        if p.name == "shell.json":
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(doc, dict) and \
                "/" + str(doc.get("route") or "").strip("/") == norm:
            return p
    return None


def _load_registry_entities(root: Path) -> dict:
    """Return the entity map compose_dashboard's field-existence check
    reads. Preference order:

    1. ``src/contracts/plan.json``'s ``entities`` — the planner's own
       registry, always present, always current for this generation.
    2. ``src/contracts/registry.json`` (test fixtures / older layouts).

    Empty dict on any failure — compose_dashboard tolerates it (falls
    back to [missing] markers on invalid refs rather than crashing).
    """
    plan_p = root / "src" / "contracts" / "plan.json"
    if plan_p.is_file():
        try:
            plan = json.loads(plan_p.read_text(encoding="utf-8"))
            ents = plan.get("entities")
            if isinstance(ents, dict) and ents:
                return ents
        except Exception as exc:  # noqa: BLE001
            log.warning("[dashboard-page-composer] unreadable plan: %s", exc)
    reg_p = root / "src" / "contracts" / "registry.json"
    if reg_p.is_file():
        try:
            reg = json.loads(reg_p.read_text(encoding="utf-8"))
            return reg.get("entities") or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("[dashboard-page-composer] unreadable registry: %s", exc)
    return {}


def _load_plan(root: Path) -> dict | None:
    p = root / "src" / "contracts" / "plan.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("[dashboard-page-composer] unreadable plan: %s", exc)
        return None


def _is_sub_dashboard(page: dict) -> bool:
    """Dashboard-typed AND not a landing route."""
    if not isinstance(page, dict):
        return False
    if page.get("type") != "dashboard":
        return False
    route = str(page.get("route") or "").strip().lower()
    if route in _LANDING_ROUTES:
        return False
    # Endswith patterns the landing composer already claims.
    for suffix in ("/dashboard", "/overview", "/home"):
        if route.endswith(suffix):
            return False
    return True


def _compose_one(page: dict, entities: dict, component_names: set[str]) -> dict:
    composition = plan_page_to_composition(page)
    # The composer authors named data sources alongside the nodes — they
    # MUST land in the page's ``dataSources`` or every ``{{binding}}`` on
    # this page is dead (the fleet's 30-point Chart contract leak).
    data_sources: list[dict] = []
    root_node = compose_dashboard(
        composition,
        entities=entities,
        component_names=component_names,
        data_sources=data_sources,
    )
    return {
        "id": page.get("name") or page.get("id") or (page.get("route") or "").strip("/") or "Page",
        "route": page.get("route"),
        "type": "dashboard",
        "dataSources": data_sources,
        "root": root_node,
    }


def compose_sub_dashboards(
    output_dir: str,
    *,
    component_names: set[str] | None = None,
) -> dict[str, Any]:
    """Compose every dashboard-typed page other than the landing route.

    Returns a diagnostic dict::

        {"composed": <int>, "skipped": <int>, "written": [route,...],
         "reason": <str, when composed=0>}

    Never raises. Per-page failures are logged and counted as skipped.

    Args:
        output_dir: generated app root.
        component_names: registered component names from the library
            manifest. Empty set is tolerated — compose_dashboard will
            swap unknown components for Table fallbacks and log.
    """
    root = Path(output_dir)
    plan = _load_plan(root)
    if not plan:
        return {"composed": 0, "skipped": 0, "written": [],
                "reason": "no plan.json"}

    pages = plan.get("pages") or []
    sub_dashes = [p for p in pages if _is_sub_dashboard(p)]
    if not sub_dashes:
        return {"composed": 0, "skipped": 0, "written": [],
                "reason": "no sub-dashboard pages"}

    entities = _load_registry_entities(root)
    comps: set[str] = set(component_names or [])
    sdir = root / "src" / "schemas"
    sdir.mkdir(parents=True, exist_ok=True)

    composed = 0
    skipped = 0
    written: list[str] = []
    for page in sub_dashes:
        route = page.get("route") or ""
        name = _route_to_schema_name(route)
        if not name:
            skipped += 1
            continue
        try:
            new_schema = _compose_one(page, entities, comps)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[dashboard-page-composer] compose failed for %s: %s", route, exc,
            )
            skipped += 1
            continue

        existing = _existing_schema_for_route(sdir, route)
        target = existing if existing is not None else (sdir / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(new_schema, indent=2, ensure_ascii=False)

        # Idempotency: skip when the on-disk file matches byte-for-byte.
        if target.is_file():
            try:
                if target.read_text(encoding="utf-8") == payload:
                    continue
            except Exception:  # noqa: BLE001
                pass

        try:
            target.write_text(payload, encoding="utf-8")
            composed += 1
            written.append(route)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[dashboard-page-composer] write failed for %s: %s", target, exc,
            )
            skipped += 1

    if composed:
        log.info(
            "[dashboard-page-composer] composed %d sub-dashboard(s): %s",
            composed, written,
        )
    return {"composed": composed, "skipped": skipped, "written": written}


__all__ = ["compose_sub_dashboards", "plan_page_to_composition"]
