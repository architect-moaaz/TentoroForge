"""Post-generate guard: bind Chart nodes to real op:"series" dataSources.

Charts are frequently emitted with a HARDCODED literal `data` array of made-up
rows (copied from the dashboard exemplar), so they render fake numbers that never
reflect the database. This guard walks every page schema, finds such charts, and
— when it can confidently map the chart to a real entity + column — replaces the
literal array with a generated op:"series" dataSource (a GROUP BY that the runtime
resolves to `[{label, value}]`) and rebinds the chart to it.

Deliberately CONSERVATIVE: if a chart can't be mapped to a real entity/column with
confidence, its mock data is left untouched — a static chart beats a broken
binding. Idempotent (already-bound charts and re-runs are no-ops). Never raises.

Contract with the runtime (data-engine.ts resolveSeries): series rows always use
keys `label` (x-axis) and `value` (y-axis), so a converted chart always gets
xKey:"label" and series:[{dataKey:"value"}].
"""
from __future__ import annotations

import glob
import json
import os
import re

from services.form_scaffold import _load_registry, _ent_key, _plural
from services.semantic_field_types import _iter_nodes, _norm

# Column types / names that indicate a date/time column suitable for bucketing.
_DATE_TYPES = {"timestamp", "timestamptz", "date", "datetime", "time"}
_DATE_NAME_RE = re.compile(r"(date|time|created|updated|_at$|day|week|month|year|quarter|period)", re.I)
# Common category columns to fall back on when the chart's xKey names nothing real.
_CATEGORY_HINTS = (
    "status", "priority", "type", "category", "source", "stage", "state",
    "kind", "tier", "level", "role", "channel", "department", "region",
)


def _cap(s: str) -> str:
    return (s[:1].upper() + s[1:]) if s else s


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


def _is_date_col(col: str, sql_type: str) -> bool:
    return (sql_type or "").lower() in _DATE_TYPES or bool(_DATE_NAME_RE.search(col or ""))


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


def _find_category_column(xkey: str, candidates: list[str], efields) -> tuple[str, str] | None:
    """An entity+column whose name matches the chart's xKey exactly (normalised)."""
    xn = _norm(xkey)
    if not xn:
        return None
    for ent in candidates:
        for col in efields.get(ent, {}):
            if _norm(col) == xn:
                return ent, col
    return None


def _rank_by_id_hint(node_id: str, legend: str, candidates: list[str]) -> list[str]:
    """Prefer entities whose name appears in the chart id / legend (e.g. a chart
    id 'dispatch-trend-chart' → the Dispatch entity)."""
    hint = _norm(f"{node_id or ''}{legend or ''}")
    if not hint:
        return candidates
    hinted = [e for e in candidates if _ent_key(e) and _ent_key(e) in hint]
    rest = [e for e in candidates if e not in hinted]
    return hinted + rest


def _plan_series(node: dict, props: dict, page_ents: list[str], efields) -> tuple[dict, str] | None:
    """Decide the series dataSource + legend name for one hardcoded chart, or None
    if it can't be mapped to a real entity/column with confidence."""
    node_id = node.get("id") or ""
    series0 = (props.get("series") or [{}])[0] if isinstance(props.get("series"), list) else {}
    legend = series0.get("name") or "Count"
    data = props.get("data") or []
    sample = data[0] if data and isinstance(data[0], dict) else {}
    measured = {series0.get("dataKey")} if series0.get("dataKey") else set()
    xkey = props.get("xKey") or next((k for k in sample if k not in measured), "")

    ranked = _rank_by_id_hint(node_id, legend, page_ents)

    # 1) Category chart — xKey names a real column on a page entity.
    hit = _find_category_column(xkey, ranked, efields)
    if hit:
        ent, col = hit
        return (
            {"name": f"{_lower1(ent)}By{_cap(col)}", "entity": ent, "op": "series",
             "groupBy": col, "agg": {"fn": "count"}, "sort": "value", "limit": 8},
            legend,
        )

    # 2) Time chart — xKey/sample keys look date-ish → group a real date column.
    keys_blob = " ".join([str(xkey)] + [str(k) for k in sample])
    if _DATE_NAME_RE.search(keys_blob):
        if re.search(r"month|year|quarter", keys_blob, re.I):
            bucket = "month"
        elif re.search(r"day|daily|hour", keys_blob, re.I):
            bucket = "day"
        else:
            bucket = "week"
        for ent in ranked:
            date_cols = [c for c, t in efields.get(ent, {}).items() if _is_date_col(c, t)]
            if date_cols:
                # Prefer a creation timestamp; else the first date column.
                col = next((c for c in date_cols if _norm(c) in ("createdat", "createddate")), date_cols[0])
                return (
                    {"name": f"{_lower1(ent)}By{_cap(bucket)}", "entity": ent, "op": "series",
                     "groupBy": col, "bucket": bucket, "agg": {"fn": "count"}, "limit": 12},
                    legend,
                )

    # 3) Category fallback — no xKey match, but a page entity has a common
    #    category column (status/priority/type/…).
    for ent in ranked:
        for hint in _CATEGORY_HINTS:
            col = next((c for c in efields.get(ent, {}) if _norm(c) == hint), None)
            if col:
                return (
                    {"name": f"{_lower1(ent)}By{_cap(col)}", "entity": ent, "op": "series",
                     "groupBy": col, "agg": {"fn": "count"}, "sort": "value", "limit": 8},
                    legend,
                )

    return None


def guard_chart_data_sources(output_dir: str) -> dict:
    """Convert hardcoded Chart data arrays into op:"series" dataSources + bindings.

    Returns {"converted": int, "skipped": int, "files": int}.
    """
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"converted": 0, "skipped": 0, "files": 0}

    efields = _entity_fields(_load_registry(output_dir))
    converted = skipped = files = 0
    asserts_logged = 0

    # Phase 3 (Dashboard Authority) — composer-authored schemas run in
    # ASSERT-only mode; log drift instead of rewriting Chart nodes.
    from services.dashboard_authority import should_assert_only

    for fp in glob.glob(os.path.join(sdir, "*.json")):
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue

        if should_assert_only(schema):
            _would = sum(
                1 for node in _iter_nodes(schema)
                if isinstance(node, dict) and node.get("type") == "Chart"
                and isinstance((node.get("props") or {}).get("data"), list)
                and (node.get("props") or {}).get("data")
            )
            if _would:
                import logging
                logging.getLogger(__name__).info(
                    "[chart_data_source_guard] ASSERT %s: composer-authored "
                    "schema has %d Chart(s) with literal data the legacy "
                    "converter would touch; leaving as-is (dashboard authority)",
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
            if not isinstance(node, dict) or node.get("type") != "Chart":
                continue
            props = node.get("props")
            if not isinstance(props, dict):
                continue
            data = props.get("data")
            # Only literal, non-empty arrays are candidates — a string ("{{…}}")
            # is already bound; leave it be (idempotency).
            if not isinstance(data, list) or not data:
                continue

            plan = _plan_series(node, props, page_ents, efields)
            if not plan:
                skipped += 1
                continue

            src, legend = plan
            name = src["name"]
            i = 2
            while name in names:
                name = f"{src['name']}{i}"
                i += 1
            src["name"] = name
            names.add(name)
            ds.append(src)

            props["data"] = "{{%s}}" % name
            props["xKey"] = "label"
            props["series"] = [{"name": legend, "dataKey": "value"}]
            converted += 1
            changed = True

        if changed:
            schema["dataSources"] = ds
            try:
                with open(fp, "w", encoding="utf-8") as fh:
                    json.dump(schema, fh, indent=2)
                files += 1
            except Exception:
                pass

    return {"converted": converted, "skipped": skipped, "files": files,
            "asserts_logged": asserts_logged}
