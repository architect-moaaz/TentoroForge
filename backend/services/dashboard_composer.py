"""Spec C1 — Dashboard composition compiler.

The planner emits an intent block for each dashboard page:

    "dashboard_composition": {
      "tiles":   [{"kind":"stat", "label":..., "calc":..., "entity":..., ...}],
      "widgets": [{"component":..., "title":..., "bindsTo":..., ...}],
      "layout":  "kpi_row_over_two_column_widgets" | ...
    }

This module:
  1. Validates every reference against real registries — component (from
     library manifest) and resource (entities + fields from the plan).
  2. Compiles the intent to a dashboard page schema (Stack + Grid of
     Stat cards + Grid of widget components).
  3. Repairs unresolvable refs: swaps in a safe fallback + logs the
     issue. Never silently drops. Never enumerates domain-specific
     recipes — the planner is the aggregator.

Pure module. Callers (post_generate_fixes / the dashboard page builder)
apply the compiled page schema; this module does NOT touch disk.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Known-calc vocabulary — the planner picks from this list.
# ────────────────────────────────────────────────────────────

KNOWN_CALCS: frozenset[str] = frozenset({
    "count", "sum", "ratio", "avg", "min", "max", "distinct",
})

# Layout presets the compiler knows how to emit. Unknown values fall
# back to a plain vertical Stack + Grid.
KNOWN_LAYOUTS: frozenset[str] = frozenset({
    "kpi_row_over_two_column_widgets",
    "kpi_row_over_single_column",
    "kpi_grid_only",
    "widgets_only",
})

# Fallback component swapped in when the planner picks an unregistered
# component name. Table is universally safe — every dashboard entity
# has SOME columns to show.
_FALLBACK_WIDGET_COMPONENT = "Table"


# ────────────────────────────────────────────────────────────
# Types
# ────────────────────────────────────────────────────────────

class CompositionError(ValueError):
    """Raised for shape errors the caller MUST fix (not repairable).

    Repairable issues (unresolved references, unknown component
    names) do NOT raise — they log + emit a `[missing]` marker and
    swap in a fallback, per Spec C1's repair contract.
    """


# ────────────────────────────────────────────────────────────
# Validation
# ────────────────────────────────────────────────────────────

def _normalize_entity_names(names: Iterable[str]) -> dict[str, str]:
    """Return {folded_lower_stripped_underscores: original_name} so a
    planner-authored ``unit`` matches a registry entity ``Unit`` or a
    ``rent_payment`` string matches ``RentPayment``."""
    out: dict[str, str] = {}
    for n in names:
        if not isinstance(n, str) or not n:
            continue
        folded = "".join(c for c in n.lower() if c.isalnum())
        out.setdefault(folded, n)
    return out


def _entity_exists(name: Any, ent_index: dict[str, str]) -> str | None:
    """Return the canonical entity name if ``name`` resolves, else None."""
    if not isinstance(name, str) or not name:
        return None
    folded = "".join(c for c in name.lower() if c.isalnum())
    return ent_index.get(folded)


def _field_exists(entity: str, field: Any, entities: dict[str, dict]) -> bool:
    """Check that entity has this field (case/format tolerant)."""
    if not isinstance(field, str) or not field:
        return False
    ent = entities.get(entity)
    if not isinstance(ent, dict):
        return False
    fields = ent.get("fields")
    if isinstance(fields, dict):
        candidates = fields.keys()
    elif isinstance(fields, list):
        candidates = (
            f.get("name") for f in fields
            if isinstance(f, dict) and isinstance(f.get("name"), str)
        )
    else:
        return False
    folded_target = "".join(c for c in field.lower() if c.isalnum())
    for c in candidates:
        if isinstance(c, str) and "".join(ch for ch in c.lower() if ch.isalnum()) == folded_target:
            return True
    return False


def _validate_tile(tile: dict, ent_index: dict[str, str], entities: dict[str, dict]) -> tuple[bool, str]:
    """Return (valid, reason). Invalid tiles are marked [missing] but the
    caller still keeps them (with a fallback body) so the dashboard's
    slot count is preserved."""
    kind = tile.get("kind")
    if kind != "stat":
        return False, f"unknown tile kind '{kind}' (only 'stat' supported)"
    calc = tile.get("calc")
    if calc not in KNOWN_CALCS:
        return False, f"unknown calc '{calc}' (known: {sorted(KNOWN_CALCS)})"
    ent_raw = tile.get("entity")
    ent_canonical = _entity_exists(ent_raw, ent_index)
    if not ent_canonical:
        return False, f"entity '{ent_raw}' not in registry"
    # Some calcs need a numeric field (sum, avg, min, max on a column).
    if calc in ("sum", "avg", "min", "max"):
        field = tile.get("field")
        if not field:
            return False, f"calc '{calc}' requires a 'field'"
        if not _field_exists(ent_canonical, field, entities):
            return False, f"field '{field}' not on entity '{ent_canonical}'"
    # `ratio` needs numerator + denominator; both should reference existing entities.
    if calc == "ratio":
        for k in ("numerator", "denominator"):
            v = tile.get(k)
            if not isinstance(v, str) or not v.strip():
                return False, f"ratio requires '{k}'"
    return True, ""


def _validate_widget(widget: dict, component_names: set[str],
                     ent_index: dict[str, str]) -> tuple[bool, str]:
    comp = widget.get("component")
    if not isinstance(comp, str) or not comp:
        return False, "widget missing 'component'"
    if comp not in component_names:
        return False, f"component '{comp}' not in library registry"
    ent = _entity_exists(widget.get("bindsTo"), ent_index)
    if not ent:
        return False, f"bindsTo '{widget.get('bindsTo')}' not in registry"
    return True, ""


# ────────────────────────────────────────────────────────────
# Compilation
# ────────────────────────────────────────────────────────────

def _label_for(col: str) -> str:
    """``interviewDate`` → ``Interview Date`` (humanized column header)."""
    s = re.sub(r"[_\-]+", " ", str(col))
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    return " ".join(w[:1].upper() + w[1:] for w in s.split())


def _unique_source_name(base: str, used: set[str]) -> str:
    name = base
    i = 2
    while name in used:
        name = f"{base}{i}"
        i += 1
    used.add(name)
    return name


def _entity_field_names(entities: dict, canonical: str | None) -> list[str]:
    """Field names for an entity, tolerating both registry field shapes."""
    ent = (entities or {}).get(canonical) if canonical else None
    fields = (ent or {}).get("fields") if isinstance(ent, dict) else None
    names: list[str] = []
    if isinstance(fields, dict):
        names = [str(k) for k in fields.keys()]
    elif isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict) and f.get("name"):
                names.append(str(f["name"]))
            elif isinstance(f, str):
                names.append(f)
    return names


_AUDIT_COLS = {"id", "createdat", "updatedat", "deletedat"}

# Column-name endings that make a sensible chart GROUP BY when the plan
# widget doesn't declare one. Ordered by preference.
_GROUPABLE_HINTS = ("status", "type", "category", "stage", "state",
                    "priority", "role", "level", "department")

_CHART_TYPES = {"line", "bar", "area", "pie", "donut", "funnel", "radar"}


def _pick_group_field(field_names: list[str]) -> str | None:
    for hint in _GROUPABLE_HINTS:
        for f in field_names:
            low = f.lower()
            if low == hint or low.endswith(hint):
                return f
    return None


def _titled_card(title: str, inner: dict) -> dict:
    """Widget chrome — mirrors deterministic_pages' _dash_card so
    composer-authored widgets look identical to deterministic ones."""
    return {
        "type": "Card",
        "props": {"variant": "surface", "padding": "md"},
        "children": [
            {"type": "Heading", "props": {"content": title, "level": 3}},
            inner,
        ],
    }


def _stat_card_node(tile: dict, canonical_entity: str | None,
                    data_sources: list[dict], used: set[str]) -> dict:
    """Compile a validated `stat` tile into a Card+Stat node bound to a
    REAL named data source (op = the tile's calc) — never a dict-shaped
    descriptor prop, which no runtime resolves."""
    label = str(tile.get("label") or "").strip() or "Stat"
    calc = str(tile.get("calc") or "count")
    name = _unique_source_name(
        f"{(canonical_entity or 'stat').lower()}_{calc}", used)
    ds: dict = {"name": name, "entity": canonical_entity, "op": calc}
    if tile.get("field"):
        ds["field"] = tile["field"]
    if tile.get("filter"):
        ds["filter"] = tile["filter"]
    data_sources.append(ds)
    return {
        "type": "Card",
        "props": {"variant": "surface", "padding": "md"},
        "children": [
            {
                "type": "Stat",
                "props": {"label": label, "value": f"{{{{{name}}}}}"},
            },
        ],
    }


def _missing_stat_card_node(tile: dict, reason: str) -> dict:
    """The [missing]-marked fallback for an invalid tile."""
    label = str(tile.get("label") or "").strip() or "Stat"
    return {
        "type": "Card",
        "props": {"variant": "surface", "padding": "md"},
        "children": [
            {
                "type": "Stat",
                "props": {
                    "label": label,
                    "value": "—",
                    "hint": f"[missing] {reason}",
                },
            },
        ],
    }


def _widget_node(widget: dict, canonical_entity: str, entities: dict,
                 data_sources: list[dict], used: set[str]) -> dict:
    """Compile a widget into a node with a REAL binding.

    Every emitted node satisfies its component contract:
      * Chart → op:"series" source + chartType/data/xKey/series (the exact
        shape apply_dashboard_maquette + deterministic_pages emit).
      * Chart with no usable groupBy → a Table of recent rows (an
        unbindable chart renders empty; a table says something).
      * Table → op:"list" source + columns [{key,label}] + rows binding.
      * Everything else list-shaped → op:"list" source + dataSource
        binding, wrapped in a titled Card.
    """
    comp = widget["component"]
    title = str(widget.get("title") or comp)
    fields = _entity_field_names(entities, canonical_entity)
    ent_l = canonical_entity.lower() if canonical_entity else "data"

    if comp in ("Chart", "Heatmap"):
        group_by = widget.get("groupBy") or _pick_group_field(fields)
        if group_by:
            name = _unique_source_name(
                f"{ent_l}_by_{str(group_by).lower()}", used)
            data_sources.append({
                "name": name, "entity": canonical_entity,
                "op": "series", "groupBy": str(group_by),
            })
            if comp == "Heatmap":
                return _titled_card(title, {
                    "type": "Heatmap",
                    "props": {"data": f"{{{{{name}}}}}"},
                })
            chart_type = str(widget.get("chartType") or "bar").lower()
            if chart_type not in _CHART_TYPES:
                chart_type = "bar"
            return {
                "type": "Chart",
                "props": {
                    "title": title,
                    "chartType": chart_type,
                    "data": f"{{{{{name}}}}}",
                    "xKey": "label",
                    "series": [{"name": title, "dataKey": "value"}],
                },
            }
        log.info("[dashboard] no groupable column on %s — composing a "
                 "Table instead of an unbindable %s", canonical_entity, comp)
        comp = "Table"

    if comp == "Table":
        name = _unique_source_name(f"{ent_l}Rows", used)
        ds = {"name": name, "entity": canonical_entity, "op": "list"}
        limit = widget.get("limit")
        if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
            ds["limit"] = limit
        data_sources.append(ds)
        raw_cols = widget.get("columns")
        wanted = [c for c in raw_cols if isinstance(c, str) and c in fields] \
            if isinstance(raw_cols, list) else []
        display = wanted or \
            [f for f in fields if f.lower() not in _AUDIT_COLS][:5] or \
            fields[:4] or ["id"]
        return _titled_card(title, {
            "type": "Table",
            "props": {
                "columns": [{"key": c, "label": _label_for(c)} for c in display],
                "rows": f"{{{{{name}}}}}",
            },
        })

    if comp in ("Stat", "MetricTile"):
        # A scalar widget bound to a list array shows nothing sensible —
        # author a count aggregate, same shape as the KPI tiles.
        name = _unique_source_name(f"{ent_l}_count", used)
        data_sources.append(
            {"name": name, "entity": canonical_entity, "op": "count"})
        props: dict = {"label": title, "value": f"{{{{{name}}}}}"}
        if comp == "MetricTile":
            props["format"] = "number"
        return {
            "type": "Card",
            "props": {"variant": "surface", "padding": "md"},
            "children": [{"type": comp, "props": props}],
        }

    name = _unique_source_name(f"{ent_l}_list", used)
    ds = {"name": name, "entity": canonical_entity, "op": "list"}
    limit = widget.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        ds["limit"] = limit
    data_sources.append(ds)
    return _titled_card(title, {
        "type": comp,
        "props": {"dataSource": f"{{{{{name}}}}}"},
    })


def _fallback_widget_node(widget: dict, reason: str) -> dict:
    return {
        "type": _FALLBACK_WIDGET_COMPONENT,
        "props": {
            "title": widget.get("title") or "Widget",
            "hint": f"[missing] {reason}",
        },
    }


def _grid(children: list[dict], cols: int) -> dict:
    """A row of peer widgets, emitted the way the renderer actually reads it.

    This emitted `cols`. Grid reads `p.columns`, as a NUMBER, and falls back to
    1 when it is absent — so every grid this built rendered as a single stacked
    column. Nothing warned: `cols` is a plausible name, it just isn't the one,
    and the drift only ever showed up as a look.

    Density comes from services.section_layout rather than being restated here.
    The post-generate pass applies the same rule to pages nobody composed; if
    the two ever disagreed, a page would change shape depending on which got
    there first.
    """
    from services.section_layout import density_for_columns

    columns = max(1, int(cols or 1))
    density = density_for_columns(columns)
    if density:
        for child in children:
            # Only Card has the prop; elsewhere it would be a dead prop that
            # reads as intent nobody implements.
            if isinstance(child, dict) and child.get("type") == "Card":
                child.setdefault("props", {}).setdefault("density", density)
    return {
        "type": "Grid",
        "props": {
            "columns": columns,
            "gap": "md",
            # Peers are read side by side: a short card beside a tall one must
            # not render ragged, and a wide table must not steal its
            # neighbours' share of the width.
            "equalRows": True,
            "equalCols": True,
        },
        "children": children,
    }


def compose_dashboard(
    composition: dict,
    *,
    entities: dict,
    component_names: set[str],
    data_sources: list[dict] | None = None,
) -> dict:
    """Compile a plan-authored composition dict into a page-schema root.

    Args:
        composition: the ``dashboard_composition`` dict from the plan.
        entities: registry ``entities`` dict — used to resolve entity + field
            references. Both ``{Name: {fields: {...}}}`` and
            ``{Name: {fields: [...]}}`` shapes are accepted.
        component_names: the set of every registered component name from
            the library manifest.

    Returns:
        A page-schema dict ``{"type": "Stack", "children": [...]}`` ready
        to be nested under a page ``root``.

    Never raises for repairable issues (unresolved refs, unknown
    components). Always returns a page — even if every reference is
    broken, callers get a stack of ``[missing]`` cards, not a crash.
    """
    if not isinstance(composition, dict):
        raise CompositionError("composition must be a dict")

    ent_index = _normalize_entity_names(entities.keys() if isinstance(entities, dict) else [])

    # Named data sources authored alongside the nodes — callers pass a
    # collector list and persist it as the page's ``dataSources``. A
    # binding like ``{{documentsRows}}`` without this list is dead.
    ds_out: list[dict] = data_sources if data_sources is not None else []
    used_names: set[str] = {
        str(d.get("name")) for d in ds_out if isinstance(d, dict) and d.get("name")
    }

    # Compile tiles first.
    tiles_out: list[dict] = []
    for tile in composition.get("tiles") or []:
        if not isinstance(tile, dict):
            continue
        ok, reason = _validate_tile(tile, ent_index, entities or {})
        if ok:
            canonical = _entity_exists(tile.get("entity"), ent_index)
            tiles_out.append(_stat_card_node(tile, canonical, ds_out, used_names))
        else:
            log.warning("[dashboard] dropping tile: %s (tile=%s)", reason, tile)
            tiles_out.append(_missing_stat_card_node(tile, reason))

    # Compile widgets.
    widgets_out: list[dict] = []
    for widget in composition.get("widgets") or []:
        if not isinstance(widget, dict):
            continue
        ok, reason = _validate_widget(widget, component_names, ent_index)
        if ok:
            canonical = _entity_exists(widget.get("bindsTo"), ent_index)
            widgets_out.append(_widget_node(widget, canonical, entities or {}, ds_out, used_names))
        else:
            log.warning("[dashboard] widget swap: %s (widget=%s)", reason, widget)
            widgets_out.append(_fallback_widget_node(widget, reason))

    # Assemble layout.
    layout = composition.get("layout")
    if layout not in KNOWN_LAYOUTS:
        layout = "kpi_row_over_two_column_widgets"

    children: list[dict] = []
    if tiles_out:
        # KPI row: 4-up on wide, 2-up on medium — deterministic Grid.
        children.append(_grid(tiles_out, cols=min(4, len(tiles_out)) or 1))
    if widgets_out:
        if layout == "kpi_grid_only":
            pass  # widgets omitted
        elif layout == "widgets_only":
            children = [_grid(widgets_out, cols=2)]
        elif layout == "kpi_row_over_single_column":
            for w in widgets_out:
                children.append(w)
        else:  # kpi_row_over_two_column_widgets (default)
            children.append(_grid(widgets_out, cols=2 if len(widgets_out) > 1 else 1))

    if not children:
        # Nothing valid at all — emit an EmptyState so the page renders.
        children = [{
            "type": "EmptyState",
            "props": {
                "title": "Dashboard is empty",
                # ``message`` is EmptyState's REQUIRED prop — description
                # alone fails the page contract.
                "message": (
                    "Planner emitted no valid tiles or widgets. "
                    "Check plan.dashboard_composition."
                ),
            },
        }]

    return {
        "type": "Stack",
        "props": {"gap": "lg"},
        "children": children,
    }


# ────────────────────────────────────────────────────────────
# Plan-level rule for the plan_completeness_validator to import.
# ────────────────────────────────────────────────────────────

def collect_violations(composition: Any, entities: dict, component_names: set[str]) -> list[str]:
    """Return a list of human-readable violation strings for a composition.

    Empty list = clean. Called by the plan validator so REVISE loops
    catch bad compositions before generation proceeds.
    """
    out: list[str] = []
    if composition is None:
        return out
    if not isinstance(composition, dict):
        out.append("dashboard_composition must be a dict")
        return out
    ent_index = _normalize_entity_names(entities.keys() if isinstance(entities, dict) else [])
    for tile in composition.get("tiles") or []:
        if not isinstance(tile, dict):
            continue
        ok, reason = _validate_tile(tile, ent_index, entities or {})
        if not ok:
            out.append(f"tile {tile.get('label') or tile.get('kind')}: {reason}")
    for widget in composition.get("widgets") or []:
        if not isinstance(widget, dict):
            continue
        ok, reason = _validate_widget(widget, component_names, ent_index)
        if not ok:
            out.append(f"widget {widget.get('title') or widget.get('component')}: {reason}")
    layout = composition.get("layout")
    if layout is not None and layout not in KNOWN_LAYOUTS:
        out.append(f"unknown layout '{layout}' (known: {sorted(KNOWN_LAYOUTS)})")
    return out


__all__ = [
    "CompositionError",
    "KNOWN_CALCS",
    "KNOWN_LAYOUTS",
    "collect_violations",
    "compose_dashboard",
]
