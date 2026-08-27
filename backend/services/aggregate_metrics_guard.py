"""Post-generate guard: fill missing ``metrics`` on op:"aggregate" dataSources.

The LLM regularly authors an aggregate dataSource like::

    { "name": "mrrSummary", "entity": "MonthlyMrrSnapshot", "op": "aggregate" }

then binds ``{{mrrSummary.newMrr}}`` / ``{{mrrSummary.expansionMrr}}`` off it.
With no ``metrics`` block, the runtime's ``resolveAggregate`` (data-engine.ts)
returns ``{}``; every dotted binding resolves to ``undefined``; the KPI tiles
render blank.

This guard closes the gap declaratively without guessing:

  1. For each op:"aggregate" dataSource ``S`` on a page, collect every
     ``{{S.<key>}}`` binding referenced anywhere in the page tree.
  2. For each ``<key>`` not already in ``S.metrics``, if the target entity has
     a numeric column whose name matches ``<key>`` case-insensitively, inject
     ``{fn: "sum", field: <realFieldName>}``.
  3. Any ``<key>`` that cannot be resolved to a numeric column on the entity
     is reported as a diagnostic (route + key) — never silently dropped.

Sibling of :mod:`services.chart_data_source_guard` (mock literal → series) and
:mod:`services.read_binding_guard` (missing dataSource → materialized) — this
covers the "aggregate declared but metrics keys omitted" case neither catches.

Idempotent; never raises. Under ``FORGE_BINDING_GATE`` strict, unresolved
diagnostics are logged at ERROR so ``capture_guard_logs`` surfaces them as
failures; otherwise WARN.
"""
from __future__ import annotations

import glob

from services.artifact_authority import should_assert_only_any
import json
import logging
import os
import re
from typing import Any

from services.form_scaffold import _load_registry
from services.semantic_field_types import _NUMERIC_TYPES, _iter_nodes, _norm

logger = logging.getLogger(__name__)

# Match any {{S.key}} (or {{S.key.rest}}) reference in a page string. Captures
# only the first two segments — deeper dotting on an aggregate binding isn't a
# thing the runtime supports.
_DOTTED_BINDING_RE = re.compile(r"\{\{\s*([A-Za-z_][\w]*)\s*\.\s*([A-Za-z_][\w]*)")


def _strict() -> bool:
    """True when FORGE_BINDING_GATE is set to a strict-mode value."""
    mode = (os.environ.get("FORGE_BINDING_GATE") or "").strip().lower()
    return mode not in ("", "warn", "off", "0", "false", "advisory")


def _entity_fields(reg: dict) -> dict[str, dict[str, str]]:
    """``{EntityName: {colName: sql_type}}`` — same shape as
    :func:`chart_data_source_guard._entity_fields`, kept in-module so this
    file has no cross-guard runtime dependency."""
    out: dict[str, dict[str, str]] = {}
    for name, e in (reg.get("entities") or {}).items():
        f = (e or {}).get("fields") if isinstance(e, dict) else None
        if isinstance(f, dict):
            out[name] = {
                c: ((d.get("type") if isinstance(d, dict) else str(d)) or "")
                for c, d in f.items()
            }
    return out


def _resolve_entity(name: Any, efields: dict[str, dict[str, str]]) -> str | None:
    if not name:
        return None
    k = _norm(name)
    for real in efields:
        if _norm(real) == k:
            return real
    return None


def _is_numeric_type(sql_type: str) -> bool:
    t = (sql_type or "").strip().lower()
    if t in _NUMERIC_TYPES:
        return True
    # Postgres "numeric(10,2)" / "decimal(10,2)" — strip the precision suffix.
    base = t.split("(", 1)[0].strip()
    return base in _NUMERIC_TYPES


def _numeric_column_for(key: str, entity_cols: dict[str, str]) -> str | None:
    """The real column name on ``entity`` whose name matches ``key``
    case-insensitively AND whose SQL type is numeric — else None."""
    kn = _norm(key)
    for col, sql_type in entity_cols.items():
        if _norm(col) == kn and _is_numeric_type(sql_type):
            return col
    return None


def _collect_binding_keys(schema: dict) -> dict[str, set[str]]:
    """Walk the page tree, return ``{sourceName: {key, ...}}`` for every
    ``{{S.key}}`` reference seen in a string value."""
    out: dict[str, set[str]] = {}

    def _scan(v: Any) -> None:
        if isinstance(v, str):
            for m in _DOTTED_BINDING_RE.finditer(v):
                out.setdefault(m.group(1), set()).add(m.group(2))
        elif isinstance(v, dict):
            for x in v.values():
                _scan(x)
        elif isinstance(v, list):
            for x in v:
                _scan(x)

    for node in _iter_nodes(schema):
        for v in node.values():
            _scan(v)
    return out


def _fill_metrics_for_source(
    ds: dict,
    referenced_keys: set[str],
    efields: dict[str, dict[str, str]],
) -> tuple[list[str], list[str]]:
    """Inject missing metric entries into ``ds`` in place.

    Returns ``(injected_keys, unresolved_keys)``. Unresolved keys are those
    referenced by the page but not backing a numeric column on the entity —
    the caller emits diagnostics for them.
    """
    entity = _resolve_entity(ds.get("entity"), efields)
    ent_cols = efields.get(entity or "", {}) if entity else {}

    metrics = ds.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}

    # Case-insensitive index of already-present metric keys so a binding of a
    # different case doesn't cause a duplicate injection.
    present = {_norm(k) for k in metrics}

    injected: list[str] = []
    unresolved: list[str] = []

    for key in sorted(referenced_keys):
        if _norm(key) in present:
            continue
        col = _numeric_column_for(key, ent_cols) if ent_cols else None
        if col:
            metrics[key] = {"fn": "sum", "field": col}
            present.add(_norm(key))
            injected.append(key)
        else:
            unresolved.append(key)

    if injected:
        ds["metrics"] = metrics
    return injected, unresolved


def guard_aggregate_metrics(output_dir: str) -> dict:
    """Fill missing ``metrics`` on op:"aggregate" dataSources.

    Returns ``{"files_scanned": int, "files_changed": int, "injected": int,
    "unresolved": [{"route": str, "source": str, "key": str}, ...]}``.
    Idempotent; never raises.
    """
    result = {
        "files_scanned": 0,
        "files_changed": 0,
        "injected": 0,
        "asserts_logged": 0,
        "unresolved": [],
    }
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return result

    try:
        efields = _entity_fields(_load_registry(output_dir))
    except Exception:  # noqa: BLE001 — a corrupt registry must never break the pipeline
        logger.exception("aggregate_metrics_guard: could not load registry")
        return result

    strict = _strict()

    for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
        if os.path.basename(fp) == "nav-flow.json":
            continue
        result["files_scanned"] += 1
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(schema, dict):
            continue

        # Composer-authored pages are ASSERT-only: the composer's decision is the
        # authority, so log drift instead of rewriting it.
        if should_assert_only_any(schema):
            result["asserts_logged"] += 1
            continue

        ds_list = schema.get("dataSources")
        if not isinstance(ds_list, list) or not ds_list:
            continue

        agg_sources = {
            ds.get("name"): ds
            for ds in ds_list
            if isinstance(ds, dict)
            and str(ds.get("op", "")).lower() == "aggregate"
            and isinstance(ds.get("name"), str)
        }
        if not agg_sources:
            continue

        refs = _collect_binding_keys(schema)
        route = schema.get("route") or os.path.relpath(fp, sdir)
        file_changed = False

        for name, ds in agg_sources.items():
            keys = refs.get(name, set())
            if not keys:
                continue
            injected, unresolved = _fill_metrics_for_source(ds, keys, efields)
            if injected:
                result["injected"] += len(injected)
                file_changed = True
                logger.info(
                    "aggregate_metrics_guard: %s (%s) injected metric(s) %s",
                    route, name, ", ".join(injected),
                )
            for k in unresolved:
                result["unresolved"].append(
                    {"route": route, "source": name, "key": k}
                )
                msg = (
                    "aggregate_metrics_guard: %s aggregate '%s' references "
                    "{{%s.%s}} with no matching numeric column on entity '%s'"
                )
                args = (route, name, name, k, ds.get("entity"))
                if strict:
                    logger.error(msg, *args)
                else:
                    logger.warning(msg, *args)

        if file_changed:
            try:
                with open(fp, "w", encoding="utf-8") as fh:
                    json.dump(schema, fh, indent=2)
                result["files_changed"] += 1
            except OSError as e:
                logger.warning(
                    "aggregate_metrics_guard: could not write %s: %s", fp, e
                )

    return result
