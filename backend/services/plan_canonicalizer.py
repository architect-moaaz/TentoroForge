"""Canonicalize the plan at the ingestion seam — one spelling downstream.

Why this exists
---------------
Every consumer of plan.json today carries tolerance code because the plan
arrives in whatever shape the planner/LLM produced: ``dataModels`` vs
``data_models``, ``columns`` vs ``fields``, ``column`` vs ``name``,
``enum_values`` at the field top level vs nested under ``semantic``, and
the same entity appearing in BOTH the ``entities`` dict and the
``data_models`` list with different metadata on each copy (the class that
broke binding_prop_normalizer's ``_unique_enum_entity`` — Document found
"twice", dedupe logic everywhere).

Per the anomaly-removal plan: normalize ONCE, at the seam where plan.json
is persisted (routers/generate.py), so every downstream reader sees one
canonical shape and its tolerance code can eventually be deleted.

Canonical shape guarantees after ``canonicalize_plan``:

- entity list lives under ``data_models`` (never ``dataModels``);
- each entity's field list lives under ``fields`` (never ``columns``);
- each field has ``name`` (backfilled from ``column`` when absent);
- ``enum_values`` is top-level on the field (hoisted from
  ``semantic.enum_values`` when only the nested spelling exists);
- ``data_models`` has ONE entry per entity (case-insensitive name),
  duplicate entries merged field-by-field;
- an entity present in both ``entities`` (dict flavour) and
  ``data_models`` carries IDENTICAL field metadata on both copies —
  fields are unioned and merged so it no longer matters which container
  a reader iterates.

The function is pure (input not mutated), idempotent, and never raises
on malformed input — garbage passes through unchanged.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _fold(s: Any) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _new_report() -> dict:
    return {"summary": {
        "containers_renamed": 0,
        "fields_named": 0,
        "enum_hoisted": 0,
        "entities_deduped": 0,
        "cross_synced": 0,
    }}


# ────────────────────────────────────────────────────────────────────
# Field / entity normalization
# ────────────────────────────────────────────────────────────────────

def _normalize_field(f: dict, summary: dict) -> dict:
    if not isinstance(f, dict):
        return f
    if "name" not in f and isinstance(f.get("column"), str):
        f["name"] = f["column"]
        summary["fields_named"] += 1
    sem = f.get("semantic")
    if "enum_values" not in f and isinstance(sem, dict):
        vals = sem.get("enum_values")
        if isinstance(vals, list) and vals:
            f["enum_values"] = vals
            summary["enum_hoisted"] += 1
    return f


def _normalize_entity(ent: dict, summary: dict) -> dict:
    if not isinstance(ent, dict):
        return ent
    if "fields" not in ent and isinstance(ent.get("columns"), list):
        ent["fields"] = ent.pop("columns")
        summary["containers_renamed"] += 1
    fields = ent.get("fields")
    if isinstance(fields, list):
        ent["fields"] = [_normalize_field(f, summary) for f in fields]
    return ent


def _merge_field(base: dict, extra: dict) -> dict:
    """Union metadata — base wins on conflicts, extra fills gaps."""
    merged = dict(extra)
    merged.update({k: v for k, v in base.items() if v is not None})
    return merged


def _merge_fields(base: list, extra: list) -> list:
    """Union two field lists by folded name; base order first."""
    out: list[dict] = []
    index: dict[str, int] = {}
    for f in base:
        if isinstance(f, dict) and isinstance(f.get("name"), str):
            index[_fold(f["name"])] = len(out)
        out.append(f)
    for f in extra:
        if not isinstance(f, dict) or not isinstance(f.get("name"), str):
            continue
        key = _fold(f["name"])
        if key in index:
            i = index[key]
            if isinstance(out[i], dict):
                out[i] = _merge_field(out[i], f)
        else:
            index[key] = len(out)
            out.append(f)
    return out


# ────────────────────────────────────────────────────────────────────
# Entry point
# ────────────────────────────────────────────────────────────────────

def canonicalize_plan(plan: Any) -> tuple[Any, dict]:
    """Return ``(canonical_plan, report)``. Never raises; never mutates."""
    report = _new_report()
    summary = report["summary"]
    if not isinstance(plan, dict):
        return plan, report
    plan = copy.deepcopy(plan)

    # 1. dataModels → data_models
    if "dataModels" in plan:
        camel = plan.pop("dataModels")
        if isinstance(camel, list):
            existing = plan.get("data_models")
            plan["data_models"] = (existing if isinstance(existing, list)
                                   else []) + camel
            summary["containers_renamed"] += 1

    # 2. Normalize every entity's field container + fields
    dm = plan.get("data_models")
    if isinstance(dm, list):
        plan["data_models"] = [
            _normalize_entity(e, summary) if isinstance(e, dict) else e
            for e in dm
        ]
    ents = plan.get("entities")
    if isinstance(ents, dict):
        for name, ent in ents.items():
            if isinstance(ent, dict):
                ents[name] = _normalize_entity(ent, summary)

    # 3. Dedupe data_models by folded entity name (merge fields)
    dm = plan.get("data_models")
    if isinstance(dm, list):
        seen: dict[str, dict] = {}
        deduped: list = []
        for e in dm:
            if not isinstance(e, dict) or not isinstance(e.get("name"), str):
                deduped.append(e)
                continue
            key = _fold(e["name"])
            prior = seen.get(key)
            if prior is None:
                seen[key] = e
                deduped.append(e)
            else:
                pf, ef = prior.get("fields"), e.get("fields")
                if isinstance(pf, list) and isinstance(ef, list):
                    prior["fields"] = _merge_fields(pf, ef)
                for k, v in e.items():
                    prior.setdefault(k, v)
                summary["entities_deduped"] += 1
        plan["data_models"] = deduped

    # 4. Cross-container sync: entities dict ↔ data_models agree
    ents = plan.get("entities")
    dm = plan.get("data_models")
    if isinstance(ents, dict) and isinstance(dm, list):
        dm_by_name = {_fold(e.get("name")): e for e in dm
                      if isinstance(e, dict) and isinstance(e.get("name"), str)}
        for name, ent in ents.items():
            if not isinstance(name, str) or not isinstance(ent, dict):
                continue
            twin = dm_by_name.get(_fold(name))
            if twin is None:
                continue
            ef, tf = ent.get("fields"), twin.get("fields")
            if isinstance(ef, list) and isinstance(tf, list):
                merged = _merge_fields(tf, ef)
                if merged != tf or merged != ef:
                    summary["cross_synced"] += 1
                twin["fields"] = merged
                ent["fields"] = copy.deepcopy(merged)

    return plan, report
