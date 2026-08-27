"""Every FK target referenced in a plan must be a declared entity.

Root cause of B-021.8: the LLM emits `Plant.nurseryLocationId` as an FK field
but forgets to declare a `NurseryLocation` entity. Downstream:
  * Schema builder emits Plant.nurseryLocationId as a loose uuid (no
    `.references()`, since the target doesn't exist).
  * Seed synthesizer never seeds NurseryLocation → 0 rows.
  * FK Select on the create/edit form loads an empty options list.
  * User can't submit the form → dead end.

Fix at the planner level (structural completeness, not repair): after the
plan is authored, walk every entity's fields, extract FK targets (by naming
convention: `<something>Id` / `<something>_id` referring to an entity name),
and ensure the target entity exists. If missing, synthesize a minimal stub
so the schema/seed pipelines have something to work with.

Rules for correctness (not-a-bandaid):
  * Structural — reads the plan shape only. No LLM.
  * Additive — never renames or removes existing entities.
  * Idempotent — running twice creates no duplicates.
  * Conservative — only synthesizes when the FK-target name is a clean
    entity-like identifier (single word, TitleCase or camelCase inferred).
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)


# ---------- helpers --------------------------------------------------------

_FK_ID_SUFFIX = re.compile(r"(?:Id|_id)$")


def _entity_name_from_fk_column(fk_col: str) -> str | None:
    """`nurseryLocationId` → `NurseryLocation`. `user_id` → `User`.
    Returns None if the name doesn't parse cleanly."""
    if not fk_col:
        return None
    stem = _FK_ID_SUFFIX.sub("", fk_col.strip())
    if not stem or stem == fk_col:
        return None  # didn't match the FK convention
    # snake_case → CamelCase
    parts = re.split(r"[_\-\s]+", stem)
    if not parts or not parts[0]:
        return None
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _all_entity_names_case_insensitive(entities: dict) -> dict[str, str]:
    """Map lc(name) → canonical name for quick lookup."""
    return {str(k).strip().lower(): k for k in entities.keys()}


def _iter_fk_columns(entity_spec: dict) -> Iterable[str]:
    fields = entity_spec.get("fields")
    if not isinstance(fields, list):
        return
    for f in fields:
        if not isinstance(f, dict):
            continue
        name = f.get("name")
        if isinstance(name, str) and _FK_ID_SUFFIX.search(name):
            # Only treat as FK if the field type is uuid/int (typical FK types)
            # OR the field explicitly declares fk metadata.
            t = str(f.get("type") or "").lower()
            if t in ("uuid", "int", "integer", "serial", "bigint") or f.get("fk") or f.get("references"):
                yield name


def _iter_relation_targets(plan: dict) -> Iterable[str]:
    """`plan.relations[].to` — the planner's explicit relation edges. If any
    of these point at an entity that doesn't exist, that's also a gap."""
    for rel in plan.get("relations") or []:
        if isinstance(rel, dict):
            to = rel.get("to")
            if isinstance(to, str) and to.strip():
                yield to.strip()


# ---------- stub synthesizer ----------------------------------------------

def _default_stub_entity(name: str) -> dict:
    """Minimal viable entity spec: id + name + timestamps. Enough for the
    schema builder to emit a real table and the seed synth to fill it with
    5-10 rows."""
    return {
        "name": name,
        "fields": [
            {"name": "id",        "type": "uuid",      "primaryKey": True},
            {"name": "name",      "type": "varchar",   "not_null": True},
            {"name": "createdAt", "type": "timestamp"},
            {"name": "updatedAt", "type": "timestamp"},
        ],
        "synthesized": True,   # marker — downstream can distinguish
    }


# ---------- public API -----------------------------------------------------

def missing_fk_targets(plan: dict) -> list[str]:
    """Return the set of entity names referenced by an FK but not declared."""
    entities = plan.get("entities")
    if not isinstance(entities, dict):
        return []
    lc = _all_entity_names_case_insensitive(entities)
    missing: list[str] = []
    seen: set[str] = set()

    # 1. Scan every entity's FK columns.
    for spec in entities.values():
        if not isinstance(spec, dict):
            continue
        for fk_col in _iter_fk_columns(spec):
            target = _entity_name_from_fk_column(fk_col)
            if not target:
                continue
            if target.lower() in lc:
                continue
            if target.lower() in seen:
                continue
            missing.append(target)
            seen.add(target.lower())

    # 2. Scan plan.relations[].to.
    for target in _iter_relation_targets(plan):
        if target.lower() in lc:
            continue
        if target.lower() in seen:
            continue
        missing.append(target)
        seen.add(target.lower())

    return missing


def ensure_fk_targets(plan: dict) -> dict:
    """For each FK-referenced target that isn't a declared entity, add a
    minimal stub. Mutates + returns the plan for chaining."""
    entities = plan.get("entities")
    if not isinstance(entities, dict):
        # If plan doesn't have entities at all, we can't fix this — bail.
        return plan
    for target in missing_fk_targets(plan):
        if target in entities:
            continue  # race-safe guard
        entities[target] = _default_stub_entity(target)
        logger.info("fk_target_completeness: synthesized stub entity %s", target)
    return plan
