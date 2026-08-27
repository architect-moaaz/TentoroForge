"""Post-generate guard: bind HARDCODED dashboard widgets to real dataSources.

Sibling to `chart_data_source_guard` (which binds Chart `data` arrays to
op:"series"). This guard covers the OTHER two widget families that ship with
mock literals copied from the dashboard exemplar:

  * Stat / KPI / progress / gauge tiles carrying a literal NUMBER in `value`
    (e.g. `"value": 128`) that really wants a live entity count → rebound to a
    generated op:"aggregate" count dataSource.
  * Plain collection widgets (List / DataList / a Table whose `rows` is a
    literal array) carrying a hardcoded array of rows → rebound to an
    op:"list" dataSource for the mapped entity.

Deliberately CONSERVATIVE, same philosophy as the chart guard: a static widget
beats a broken binding, so a literal is only converted when the widget maps to a
real registry entity with confidence. Everything else — genuinely-static process
templates (ApprovalStepper, ValidationChecklist), audit-log widgets with no
backing entity (ActivityFeed), config arrays (Table `columns`, Select `options`,
FilterBar `chips`), headers/help text — is left untouched.

Shape-specialized widgets are NOT in the allowlists precisely because their
literal is either config or a bespoke shape that a plain entity row can't fill.

Idempotent (already-bound `{{…}}` props and re-runs are no-ops). Never raises.

Runtime contract:
  * aggregate — {name, entity, op:"aggregate", metrics:{value:{fn:"count"}}},
    bound as `{{name.value}}` (see data-engine resolveAggregate / dashboardStats).
  * list — {name, entity, op:"list", limit}, bound as `{{name}}`.
"""
from __future__ import annotations

import glob
import json
import os
import re

from services.form_scaffold import _load_registry, _ent_key, _plural
from services.semantic_field_types import _iter_nodes, _norm

# --- Widget allowlists -------------------------------------------------------
# Normalised component type -> ordered value props to check for a literal number.
_STAT_WIDGETS: dict[str, tuple[str, ...]] = {
    "metrictile": ("value",),
    "stattile": ("value",),
    "statcard": ("value",),
    "stat": ("value",),
    "metric": ("value",),
    "metriccard": ("value",),
    "kpi": ("value",),
    "kpicard": ("value",),
    "kpitile": ("value",),
    "bignumber": ("value",),
    "counter": ("value", "count"),
    "scorecard": ("value", "score"),
    "gauge": ("value", "current"),
    "progress": ("value", "current"),
    "progressbar": ("value", "current"),
    "progressring": ("value", "current"),
}

# Normalised component type -> ordered array props to check for a literal list.
_LIST_WIDGETS: dict[str, tuple[str, ...]] = {
    "list": ("items", "data", "records"),
    "datalist": ("items", "data", "records"),
    "cardlist": ("items", "data", "records"),
    "itemlist": ("items", "data", "records"),
    "recordlist": ("items", "data", "records"),
    "listview": ("items", "data", "records"),
    "table": ("rows",),  # NEVER `columns` (that is config)
    "datatable": ("rows",),
    "datagrid": ("rows",),
}

# Count-noise words stripped from a stat label before matching it to an entity.
# If ANYTHING survives beyond the entity name, the tile has a qualifier we can't
# safely express as a plain count (e.g. "Active Drives") → skip rather than emit
# a subtly-wrong total.
_COUNT_NOISE = {
    "total", "count", "all", "number", "num", "of", "the", "tally",
    "amount", "sum", "overall", "current",
}


def _lower1(s: str) -> str:
    return (s[:1].lower() + s[1:]) if s else s


def _entity_fields(reg: dict) -> dict[str, dict[str, str]]:
    """{EntityName: {columnName: sql_type}} from the extracted registry."""
    out: dict[str, dict[str, str]] = {}
    for name, e in (reg.get("entities") or {}).items():
        f = (e or {}).get("fields") if isinstance(e, dict) else None
        if isinstance(f, dict):
            out[name] = {
                c: (d.get("type") if isinstance(d, dict) else str(d)) or ""
                for c, d in f.items()
            }
    return out


def _resolve_entity(name, efields: dict[str, dict[str, str]]) -> str | None:
    """Map a dataSource's entity string to a real registry entity name."""
    if not name:
        return None
    k = _ent_key(name)
    for real in efields:
        if _ent_key(real) == k:
            return real
    return None


def _page_entities(schema: dict, efields: dict[str, dict[str, str]]) -> list[str]:
    """Real entities this page already pulls data from (dedup, order-preserving)."""
    out: list[str] = []
    for ds in schema.get("dataSources") or []:
        if not isinstance(ds, dict):
            continue
        real = _resolve_entity(ds.get("entity"), efields)
        if real and real not in out:
            out.append(real)
    return out


def _match_entity_whole(hint: str, entities: list[str]) -> str | None:
    """The single entity whose singular key equals the hint's meaningful tokens
    once count-noise words are removed. Returns None if the hint carries an
    unmapped qualifier (so we don't emit a subtly-wrong count) or is ambiguous."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", str(hint or "").lower()) if t]
    tokens = [t for t in tokens if t not in _COUNT_NOISE]
    if not tokens:
        return None
    core = _ent_key("".join(tokens))
    matches = [e for e in entities if _ent_key(e) == core or _ent_key(_plural(e)) == core]
    if len(matches) == 1:
        return matches[0]
    return None


def _match_entity_hint(hint: str, page_ents: list[str], all_ents: list[str]) -> str | None:
    """An entity whose singular key appears as a substring of the (normalised)
    hint. Page entities win; a unique global hit is the fallback."""
    h = _norm(hint)
    if not h:
        return None
    for pool in (page_ents, all_ents):
        hits = [e for e in pool if _ent_key(e) and _ent_key(e) in h]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            # Prefer the longest (most specific) entity key on a tie.
            hits.sort(key=lambda e: len(_ent_key(e)), reverse=True)
            if len(_ent_key(hits[0])) > len(_ent_key(hits[1])):
                return hits[0]
    return None


def _uniq_name(base: str, taken: set[str]) -> str:
    name = base
    i = 2
    while name in taken:
        name = f"{base}{i}"
        i += 1
    taken.add(name)
    return name


def _try_stat(node: dict, page_ents, all_ents) -> tuple[str, dict, str] | None:
    """(value_prop, aggregate_dataSource, binding) for a stat tile, or None."""
    props = node.get("props")
    if not isinstance(props, dict):
        return None
    tkey = _norm(node.get("type"))
    value_props = _STAT_WIDGETS.get(tkey)
    if not value_props:
        return None
    prop = next(
        (p for p in value_props
         if isinstance(props.get(p), (int, float)) and not isinstance(props.get(p), bool)),
        None,
    )
    if prop is None:
        return None
    # Only the human label decides a stat's entity — the node id (e.g. "kpi",
    # "kpi-total") is noise that would defeat the strict whole-name match.
    hint = " ".join(str(props.get(k) or "") for k in ("label", "title", "name"))
    ent = _match_entity_whole(hint, page_ents or all_ents) or _match_entity_whole(hint, all_ents)
    if not ent:
        return None
    ds = {"name": f"{_lower1(ent)}Total", "entity": ent, "op": "aggregate",
          "metrics": {"value": {"fn": "count"}}}
    return prop, ds, "{{%s.value}}" % ds["name"]


def _try_list(node: dict, page_ents, all_ents) -> tuple[str, dict, str] | None:
    """(array_prop, list_dataSource, binding) for a collection widget, or None."""
    props = node.get("props")
    if not isinstance(props, dict):
        return None
    tkey = _norm(node.get("type"))
    array_props = _LIST_WIDGETS.get(tkey)
    if not array_props:
        return None
    prop = next(
        (p for p in array_props
         if isinstance(props.get(p), list) and props.get(p)
         and isinstance(props.get(p)[0], dict)),
        None,
    )
    if prop is None:
        return None
    hint = " ".join(str(props.get(k) or "") for k in ("title", "label", "name")) + " " + str(node.get("id") or "")
    ent = _match_entity_hint(hint, page_ents, all_ents)
    if not ent:
        return None
    ds = {"name": _plural(ent), "entity": ent, "op": "list", "limit": 20}
    return prop, ds, "{{%s}}" % ds["name"]


def bind_static_widgets(output_dir: str) -> dict:
    """Rebind hardcoded stat/list widgets to real aggregate/list dataSources.

    Returns {"bound": int, "skipped": int, "files": int}.
    """
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"bound": 0, "skipped": 0, "files": 0}

    efields = _entity_fields(_load_registry(output_dir))
    all_ents = list(efields.keys())
    bound = skipped = files = 0
    asserts_logged = 0

    # Phase 3 (Dashboard Authority) — composer-authored schemas run in
    # ASSERT-only mode; log drift instead of rebinding.
    from services.dashboard_authority import should_assert_only

    for fp in glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True):
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        if not isinstance(schema, dict):
            continue

        if should_assert_only(schema):
            # Count what we WOULD rebind, then move on without mutating.
            _would = 0
            for node in _iter_nodes(schema):
                if not isinstance(node, dict) or "type" not in node:
                    continue
                tkey = _norm(node.get("type"))
                if tkey in _STAT_WIDGETS or tkey in _LIST_WIDGETS:
                    _would += 1
            if _would:
                import logging
                logging.getLogger(__name__).info(
                    "[widget_data_source_guard] ASSERT %s: composer-authored "
                    "schema has %d widget(s) the legacy binder would touch; "
                    "leaving as-is (dashboard authority)",
                    os.path.basename(fp), _would,
                )
                asserts_logged += 1
            continue

        ds = schema.get("dataSources")
        if not isinstance(ds, list):
            ds = []
        names = {d.get("name") for d in ds if isinstance(d, dict)}
        page_ents = _page_entities(schema, efields)
        changed = False

        for node in _iter_nodes(schema):
            if not isinstance(node, dict) or "type" not in node:
                continue
            tkey = _norm(node.get("type"))
            if tkey not in _STAT_WIDGETS and tkey not in _LIST_WIDGETS:
                continue

            plan = _try_stat(node, page_ents, all_ents) or _try_list(node, page_ents, all_ents)
            if not plan:
                # A widget we know how to bind but couldn't map with confidence.
                props = node.get("props")
                if isinstance(props, dict):
                    skipped += 1
                continue

            prop, src, _binding = plan
            src["name"] = _uniq_name(src["name"], names)
            # Rebuild binding against the (possibly deduped) final name.
            binding = ("{{%s.value}}" if src["op"] == "aggregate" else "{{%s}}") % src["name"]
            ds.append(src)
            node["props"][prop] = binding
            bound += 1
            changed = True

        if changed:
            schema["dataSources"] = ds
            try:
                with open(fp, "w", encoding="utf-8") as fh:
                    json.dump(schema, fh, indent=2)
                files += 1
            except Exception:
                pass

    return {"bound": bound, "skipped": skipped, "files": files,
            "asserts_logged": asserts_logged}
