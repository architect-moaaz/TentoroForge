"""Reconcile dashboard MetricTile bindings with the metrics computed by an
op:"aggregate" dataSource, so {{dashboardStats.todayCount}} resolves to a real
number instead of rendering the literal template string."""
from __future__ import annotations
import re

_BINDING_RE = re.compile(r"\{\{\s*([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s*\}\}")


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


# The page agent uses BOTH "aggregate" and "stats" for KPI/metric dataSources.
# Treat them the same — the floor normalises "stats" → "aggregate" so the runtime
# (which resolves op:"aggregate" into a stats object) computes either one.
_AGG_OPS = ("aggregate", "stats")


def find_aggregate_bindings(page: dict) -> dict[str, set[str]]:
    """Map each aggregate/stats dataSource name → the set of fields MetricTiles bind to it."""
    agg_names = {
        ds.get("name")
        for ds in (page.get("dataSources") or [])
        if ds.get("op") in _AGG_OPS and ds.get("name")
    }
    found: dict[str, set[str]] = {}
    for node in _walk(page.get("root") or page):
        if not isinstance(node, dict):
            continue
        for val in (node.get("props") or {}).values():
            if not isinstance(val, str):
                continue
            for src, field in _BINDING_RE.findall(val):
                if src in agg_names:
                    found.setdefault(src, set()).add(field)
    return found


_SUM_FIELDS = ("total", "amount", "price", "revenue", "cost", "value")


def synthesise_metric(field_name: str, entity: str, entity_fields: dict[str, set[str]]) -> dict:
    """Best-effort metric for a binding the agent didn't declare. ALWAYS returns a
    computable metric (worst case: count of the entity), so the binding resolves to a
    number rather than a literal {{…}}."""
    lname = field_name.lower()
    fields = entity_fields.get(entity, set())

    window = None
    if lname.startswith("today") or "today" in lname:
        window = "today"
    elif lname.startswith("week") or "weekly" in lname or "thisweek" in lname:
        window = "week"
    elif lname.startswith("month") or "monthly" in lname or "thismonth" in lname:
        window = "month"

    metric: dict = {"fn": "count", "entity": entity}

    wants_sum = any(tok in lname for tok in ("revenue", "total", "amount", "sum", "sales"))
    wants_avg = "avg" in lname or "average" in lname or "mean" in lname
    if wants_sum or wants_avg:
        sum_field = next((f for f in _SUM_FIELDS if f in fields), None)
        if sum_field:
            metric["fn"] = "avg" if wants_avg else "sum"
            metric["field"] = sum_field
        # else: keep count — never emit a sum/avg without a real column

    if window:
        metric["window"] = window
        metric["dateField"] = "date" if "date" in fields else "createdAt"
    return metric


_VALID_FNS = {"count", "sum", "avg", "min", "max"}


def _entity_fields(registry: dict) -> dict[str, set[str]]:
    """Map entity name → set of field names. Tolerant of the shapes registry.json
    actually uses: `fields` may be a dict ({fieldName: {...}}), a list of
    {"name": ...} dicts, or a plain list of field-name strings."""
    out: dict[str, set[str]] = {}
    for name, ent in (registry.get("entities") or {}).items():
        if not isinstance(ent, dict):
            continue
        fields = ent.get("fields")
        names: set[str] = set()
        if isinstance(fields, dict):
            names = {k for k in fields if isinstance(k, str)}
        elif isinstance(fields, list):
            for f in fields:
                if isinstance(f, dict) and f.get("name"):
                    names.add(f["name"])
                elif isinstance(f, str):
                    names.add(f)
        out[name] = names
    return out


def _validate_simple(metric: dict, default_entity: str, fields: dict[str, set[str]]) -> tuple[dict, bool]:
    """Validate a PLAIN aggregate metric (fn/field/window). A sum/avg/min/max whose
    field is absent (or whose entity is unknown) is demoted to count so it always
    computes."""
    m = dict(metric)
    entity = m.get("entity") or default_entity
    m["entity"] = entity
    fn = m.get("fn") if m.get("fn") in _VALID_FNS else "count"
    m["fn"] = fn
    demoted = False
    if fn != "count":
        field = m.get("field")
        known = fields.get(entity) or set()
        ok = bool(field) and field in known
        # `expr` — arithmetic over columns ("quantity * price"), for a value no
        # single column holds. Valid when every identifier it names is a real
        # column of the entity; the data engine compiles it to SQL and the
        # editor preview evaluates it per row. Demoting this to count is what
        # turned "Total Inventory Value" into a row count.
        expr = m.get("expr")
        if not ok and isinstance(expr, str) and expr.strip():
            idents = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
            ok = bool(idents) and idents <= known
        if not ok:
            m = {"fn": "count", "entity": entity}
            for k in ("window", "dateField", "filter"):
                if k in metric:
                    m[k] = metric[k]
            demoted = True
    return m, demoted


def _validate_metric(metric: dict, default_entity: str, fields: dict[str, set[str]]) -> tuple[dict, bool]:
    """Return (clean_metric, demoted). Dispatches on the metric's `kind`:
      • ratio → validate the numerator & denominator sub-metrics, keep the shape
      • delta → validate its own fn/field, keep kind + window + percent
      • plain → simple validation (sum/avg without a real field → count)
    Without this dispatch, ratio/delta metrics (which carry no top-level `fn`) would
    be silently rewritten into a plain count, stripping the feature."""
    m = metric if isinstance(metric, dict) else {}
    # ONE DIALECT FIRST. The page composer writes
    # `{"expression": "sum(quantity * price)", "format": "currency"}`; nothing
    # downstream parses that, so the metric arrived here with no `fn` and was
    # rewritten into a plain count — a currency tile showing a row count. The
    # translation happens before validation so the demote-to-count rule below
    # judges the real function, not the absence of one.
    from services.metric_dialect import normalize_metric
    m = normalize_metric(m) or m
    kind = m.get("kind")
    entity = m.get("entity") or default_entity

    if kind == "ratio":
        out: dict = {"kind": "ratio", "entity": entity}
        if "percent" in m:
            out["percent"] = m["percent"]
        demoted = False
        for sub in ("numerator", "denominator"):
            s = m.get(sub)
            if isinstance(s, dict):
                out[sub], d = _validate_simple(s, entity, fields)
                demoted = demoted or d
            else:
                out[sub] = {"fn": "count", "entity": entity}
                demoted = True
        return out, demoted

    if kind == "delta":
        clean, demoted = _validate_simple(m, entity, fields)
        clean["kind"] = "delta"
        # a delta needs a period; default to month when the agent omits/mis-types it.
        clean["window"] = m.get("window") if m.get("window") in ("today", "week", "month") else "month"
        if "percent" in m:
            clean["percent"] = m["percent"]
        return clean, demoted

    return _validate_simple(m, default_entity, fields)


def reconcile_aggregate_specs(page: dict, registry: dict) -> tuple[dict, dict]:
    """Ensure every MetricTile binding to an aggregate source has a valid, computable
    metric. Mutates a copy of `page`; returns (page, report)."""
    import copy
    page = copy.deepcopy(page)
    fields = _entity_fields(registry)
    bindings = find_aggregate_bindings(page)
    report = {"synthesised": 0, "demoted": 0, "normalised": 0}

    for ds in page.get("dataSources") or []:
        if ds.get("op") not in _AGG_OPS:
            continue
        # Normalise "stats" → "aggregate" so the runtime resolver handles it.
        if ds.get("op") != "aggregate":
            ds["op"] = "aggregate"
            report["normalised"] += 1
        name = ds.get("name")
        default_entity = ds.get("entity") or ""
        metrics = dict(ds.get("metrics") or {})

        # Validate / demote agent-supplied metrics.
        for key, metric in list(metrics.items()):
            clean, demoted = _validate_metric(metric or {}, default_entity, fields)
            metrics[key] = clean
            report["demoted"] += int(demoted)

        # Synthesise any field a MetricTile references but the spec lacks.
        for field in bindings.get(name, set()):
            if field not in metrics:
                metrics[field] = synthesise_metric(field, default_entity, fields)
                report["synthesised"] += 1

        ds["metrics"] = metrics
    return page, report


import json as _json
from pathlib import Path


def reconcile_page_file(path: "Path", registry: dict) -> dict:
    """Load a page schema JSON, reconcile its aggregate specs, write it back. Returns the report."""
    try:
        page = _json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {"synthesised": 0, "demoted": 0, "error": "unreadable"}
    out, report = reconcile_aggregate_specs(page, registry or {})
    if report["synthesised"] or report["demoted"] or report.get("normalised"):
        Path(path).write_text(_json.dumps(out, indent=2), encoding="utf-8")
    return report
