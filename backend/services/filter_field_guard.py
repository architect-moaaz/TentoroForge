"""Fix filters that target the wrong field.

The LLM sometimes writes a filter value onto a sibling field — e.g. a dashboard
"active members" metric filters `membershipTier = "Active"`, but membershipTier is
Bronze/Silver/Gold; "Active" is a `status` value. The count is then always 0.

Using the seed plan's sample rows as ground truth for each field's real values, this
pass checks every dataSource / aggregate-metric filter: if the value doesn't belong
to the field it's on but UNAMBIGUOUSLY belongs to exactly one other field of the same
entity, it remaps the filter to that field. Deterministic + idempotent; when the
value is valid, ambiguous, or unknown, the filter is left untouched.
"""
from __future__ import annotations

import glob

from services.artifact_authority import should_assert_only_any
import json
import os

from services.form_scaffold import _ent_key, _iter_nodes, _load_registry
from services.semantic_field_types import _norm


def _field_values(seed_plan: dict) -> dict[str, dict[str, set]]:
    """{entity_key -> {realFieldName -> set(observed string values)}} from seed rows."""
    out: dict[str, dict[str, set]] = {}
    for t in (seed_plan.get("tables") or []):
        name, rows = t.get("name"), t.get("seed_data") or []
        if not name or not isinstance(rows, list):
            continue
        fv = out.setdefault(_ent_key(name), {})
        for row in rows:
            if not isinstance(row, dict):
                continue
            for k, v in row.items():
                # short, non-id string values look like enum/status categories.
                if isinstance(v, str) and v and len(v) <= 40 and not _norm(k).endswith("id"):
                    fv.setdefault(k, set()).add(v)
    return out


def _load_seed_plan(output_dir: str) -> dict:
    for rel in ("contracts/seed-plan.json", "src/contracts/seed-plan.json"):
        try:
            with open(os.path.join(output_dir, rel), encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            continue
    return {}


def _remap_field(fv_ent: dict[str, set], field: str, value) -> str | None:
    """The correct field for `value` if `field` is wrong and exactly one other fits."""
    if not isinstance(value, str) or not fv_ent:
        return None
    on_field = fv_ent.get(field)
    if on_field is not None and value in on_field:
        return None  # already correct
    hits = [f for f, vals in fv_ent.items() if f != field and value in vals]
    return hits[0] if len(hits) == 1 else None


def _fix_filter(filt: dict, ent_key: str, fv: dict[str, dict[str, set]]) -> int:
    fv_ent = fv.get(ent_key or "", {})
    fixed = 0
    for field in list(filt.keys()):
        target = _remap_field(fv_ent, field, filt.get(field))
        if target:
            filt[target] = filt.pop(field)
            fixed += 1
    return fixed


def guard_filter_fields(output_dir: str) -> dict:
    """Remap mis-fielded dataSource/metric filters. Returns {remapped, files}."""
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"remapped": 0, "files": 0, "asserts_logged": 0}
    fv = _field_values(_load_seed_plan(output_dir))
    if not fv:
        return {"remapped": 0, "files": 0, "asserts_logged": 0}
    entities = (_load_registry(output_dir).get("entities")) or {}
    ekeys = {_ent_key(n) for n in entities}

    remapped = touched = asserts_logged = 0
    for fp in glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True):
        try:
            schema = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        # Composer-authored pages are ASSERT-only: the composer's decision is the
        # authority, so log drift instead of rewriting it.
        if isinstance(schema, dict) and should_assert_only_any(schema):
            asserts_logged += 1
            continue
        changed = 0
        for ds in (schema.get("dataSources") or []):
            if not isinstance(ds, dict):
                continue
            ds_ent = _ent_key(ds.get("entity")) if ds.get("entity") else None
            if isinstance(ds.get("filter"), dict):
                changed += _fix_filter(ds["filter"], ds_ent, fv)
            for m in (ds.get("metrics") or {}).values():
                if isinstance(m, dict) and isinstance(m.get("filter"), dict):
                    m_ent = _ent_key(m.get("entity")) if m.get("entity") else ds_ent
                    if m_ent in ekeys or m_ent in fv:
                        changed += _fix_filter(m["filter"], m_ent, fv)
        if changed:
            touched += 1
            remapped += changed
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)
    return {"remapped": remapped, "files": touched,
            "asserts_logged": asserts_logged}
