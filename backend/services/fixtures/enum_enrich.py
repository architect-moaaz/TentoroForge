"""Editor-preview fixture enrichment: distribute realistic enum values.

The LLM/faker fixture layers produce records whose enum-ish columns (status,
priority, type, …) are often constant or unset — so a dashboard's KPI metric
filters (`status: "active"`) match nothing (tiles read 0) and a chart's series
`groupBy` collapses to a single bucket (one bar). This pass reads what the page
schemas actually EXPECT — the values that aggregate metric filters test for and
the columns series charts group by — and distributes those values across each
entity's rows so KPIs light up and charts get multiple buckets.

Deterministic + in-place, editor-preview only (the generated app uses real DB
rows). Never raises.
"""
from __future__ import annotations

import glob
import json
import os
import re

_DATE_RE = re.compile(r"(date|time|created|updated|_at$|at$|when|scheduled|day|week|month|year|quarter)", re.I)

# Extra variety merged in for enum-ish columns, so a column filtered on a single
# value (e.g. priority == "critical") still yields multiple chart buckets.
_ENUM_DEFAULTS: dict[str, list[str]] = {
    "status":   ["active", "pending", "completed", "cancelled"],
    "priority": ["low", "medium", "high", "critical"],
    "severity": ["low", "medium", "high", "critical"],
    "type":     ["standard", "express", "scheduled", "emergency"],
    "category": ["general", "urgent", "routine", "special"],
    "stage":    ["new", "in_progress", "review", "done"],
    "state":    ["open", "in_progress", "closed"],
    "tier":     ["basic", "standard", "premium"],
    "level":    ["low", "medium", "high"],
}

_norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _defaults_for(col: str) -> list[str]:
    n = _norm(col)
    for kw, vals in _ENUM_DEFAULTS.items():
        if kw in n:
            return list(vals)
    return []


def _dedup(seq) -> list:
    seen: set = set()
    out: list = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def harvest_value_pools(schemas_dir: str) -> dict[str, dict[str, list]]:
    """{EntityName: {column: [values]}} — the values each entity's column should
    take so KPI filters match and chart groupBy buckets are populated.

    Sources, per column: aggregate metric filter values (kept first, so they're
    guaranteed to appear), then keyword defaults for extra variety. A series
    groupBy column with no filter still gets keyword defaults.
    """
    # entity -> col -> {"filters": [values in order], "referenced": bool}
    acc: dict[str, dict[str, dict]] = {}

    def touch(entity, col):
        if not entity or not col:
            return None
        e = acc.setdefault(entity, {})
        return e.setdefault(col, {"filters": [], "referenced": True})

    if not os.path.isdir(schemas_dir):
        return {}
    for fp in glob.glob(os.path.join(schemas_dir, "*.json")):
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        for ds in schema.get("dataSources") or []:
            if not isinstance(ds, dict):
                continue
            op = ds.get("op")
            src_entity = ds.get("entity")
            if op == "aggregate":
                for m in (ds.get("metrics") or {}).values():
                    if not isinstance(m, dict):
                        continue
                    ent = m.get("entity") or src_entity
                    for k, v in (m.get("filter") or {}).items():
                        cell = touch(ent, k)
                        if cell is not None and v is not None:
                            cell["filters"].append(v)
            elif op == "series":
                col = ds.get("groupBy")
                if col and not _DATE_RE.search(col):
                    touch(src_entity, col)

    # Materialise pools: filter values first (guaranteed to appear), then defaults.
    pools: dict[str, dict[str, list]] = {}
    for entity, cols in acc.items():
        for col, info in cols.items():
            pool = _dedup([*info["filters"], *_defaults_for(col)])
            if pool:
                pools.setdefault(entity, {})[col] = pool
    return pools


def enrich_records(data: dict[str, list], pools: dict[str, dict[str, list]]) -> int:
    """In-place: round-robin each pool's values across the entity's rows. `data`
    may contain alias keys pointing at the same list object — each unique list is
    enriched once. Returns the number of (entity, column) fields filled.
    """
    if not pools:
        return 0
    # Index data keys by normalised name for case-insensitive entity matching.
    by_norm: dict[str, list] = {}
    for k, v in data.items():
        if isinstance(v, list):
            by_norm.setdefault(_norm(k), v)

    filled = 0
    processed: set[int] = set()
    for entity, cols in pools.items():
        rows = data.get(entity)
        if not isinstance(rows, list):
            rows = by_norm.get(_norm(entity))
        if not isinstance(rows, list) or not rows:
            continue
        if id(rows) in processed:
            continue
        processed.add(id(rows))
        for col, pool in cols.items():
            if not pool:
                continue
            for i, row in enumerate(rows):
                if isinstance(row, dict):
                    row[col] = pool[i % len(pool)]
            filled += 1
    return filled


def enrich_preview_data(data: dict[str, list], schemas_dir: str) -> int:
    """Convenience: harvest pools from the page schemas and enrich `data`."""
    try:
        return enrich_records(data, harvest_value_pools(schemas_dir))
    except Exception:
        return 0
