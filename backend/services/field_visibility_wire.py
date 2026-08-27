"""Materialize ``plan['field_visibility']`` into per-field metadata.

The third primitive in the wire-pass pattern. Turns a declaration
that "field F on entity E must be hidden from role R" into a
``hidden_from_roles: [R]`` annotation on the field, which downstream
form-builder + detail-page builder read to omit the field for those
roles.

Runtime column-masking at the data-runtime layer (so the API itself
never returns the field for unauthorized roles) is a follow-up slice.
This pass only reshapes the plan; the data-engine still needs to
learn to consult the annotation.

Plan slot
---------
::

    "field_visibility": [
        {"entity": "Feedback", "field": "notes",
         "hide_from_roles": ["candidate"]},
        {"entity": "Candidate", "field": "passport_number",
         "hide_from_roles": ["interviewer", "recruiter"]},
    ]

Malformed entries are silently dropped so a bad declaration never
fails generation.
"""
from __future__ import annotations

import copy
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def is_field_visibility_enabled() -> bool:
    return os.getenv("FORGE_FIELD_VISIBILITY", "").lower() in (
        "1", "true", "yes", "on",
    )


def wire_field_visibility(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a new plan with field-visibility declarations materialized.

    No-op when the plan has no ``field_visibility`` slot. Never mutates
    input. Never raises.
    """
    if not isinstance(plan, dict):
        return plan
    declarations = _read_declarations(plan)
    if not declarations:
        return dict(plan)

    new_plan = copy.deepcopy(plan)

    # Group declarations by (entity, field) so multiple hides for the
    # same field merge instead of collide.
    grouped: dict[tuple[str, str], set[str]] = {}
    for d in declarations:
        key = (d["entity"], d["field"])
        grouped.setdefault(key, set()).update(d["hide_from_roles"])

    _annotate_entity_fields(new_plan, grouped)
    _annotate_page_fields(new_plan, grouped)

    return new_plan


# ────────────────────────────────────────────────────────────
# Declaration normalization
# ────────────────────────────────────────────────────────────

def _read_declarations(plan: dict) -> list[dict]:
    raw = plan.get("field_visibility")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity")
        field = item.get("field")
        if not (isinstance(entity, str) and entity.strip()):
            continue
        if not (isinstance(field, str) and field.strip()):
            continue
        roles_raw = item.get("hide_from_roles") or []
        if not isinstance(roles_raw, list):
            continue
        roles = [r.strip() for r in roles_raw
                 if isinstance(r, str) and r.strip()]
        if not roles:
            continue
        out.append({
            "entity":          entity.strip(),
            "field":           field.strip(),
            "hide_from_roles": roles,
        })
    return out


# ────────────────────────────────────────────────────────────
# Entity-schema annotation
# ────────────────────────────────────────────────────────────

def _entities_key(plan: dict) -> str:
    if "data_models" in plan:
        return "data_models"
    if "dataModels" in plan:
        return "dataModels"
    return "entities"


def _annotate_entity_fields(
    plan: dict,
    grouped: dict[tuple[str, str], set[str]],
) -> None:
    """Add ``hidden_from_roles`` metadata to the entity-schema field.

    Idempotent — merging with any existing ``hidden_from_roles`` set."""
    key = _entities_key(plan)
    ents = plan.get(key)
    if not isinstance(ents, list):
        return

    for ent in ents:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name") or ent.get("entity") or "")
        fields = ent.get("fields")
        if not isinstance(fields, list):
            continue
        for f in fields:
            if not isinstance(f, dict):
                continue
            fname = str(f.get("name") or "")
            key_tuple = (name, fname)
            if key_tuple not in grouped:
                continue
            existing = f.get("hidden_from_roles") or []
            if not isinstance(existing, list):
                existing = []
            merged = sorted(set(existing) | grouped[key_tuple])
            f["hidden_from_roles"] = merged


# ────────────────────────────────────────────────────────────
# Page-field annotation
# ────────────────────────────────────────────────────────────

def _annotate_page_fields(
    plan: dict,
    grouped: dict[tuple[str, str], set[str]],
) -> None:
    """Some builders read field lists off the PAGE (`page['fields']` /
    `page['columns']`) not the entity. Annotate those too so the
    hide-from-roles metadata rides along.

    Only pages bound to a tracked entity get annotated — pages with no
    ``entity`` are untouched."""
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return

    entities_seen = {ent for (ent, _f) in grouped.keys()}
    for p in pages:
        if not isinstance(p, dict):
            continue
        ent = str(p.get("entity") or "")
        if ent not in entities_seen:
            continue
        fields = p.get("fields")
        if isinstance(fields, list):
            for f in fields:
                if not isinstance(f, dict):
                    continue
                fname = str(f.get("name") or "")
                key_tuple = (ent, fname)
                if key_tuple not in grouped:
                    continue
                existing = f.get("hidden_from_roles") or []
                if not isinstance(existing, list):
                    existing = []
                merged = sorted(set(existing) | grouped[key_tuple])
                f["hidden_from_roles"] = merged
