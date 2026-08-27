"""Read plan-declared field metadata for downstream constructive agents.

Bug this exists to prevent
------------------------
Bug 2 in the cabin-crew ATS: the Status dropdown on every application form
was polluted with entity names ("Application", "Drive"), duplicate-humanized
labels ("rejected" AND "Rejected Status"), and workflow strings. Root cause:
the enum-harvester in :mod:`services.post_generate_fixes` merged three sources
and had no authoritative one to prefer.

The fix, per the complete-plan-schema spec: when the plan declares
``entities[].fields[].enum_values`` for a column, THAT list is the ONLY source
for the Select's options. This module is the single reader — every downstream
guard, form scaffolder, and enum resolver reads from here, so the plan's
authority propagates without each caller re-implementing lookup logic.

Contract
--------
- ``load_plan(output_dir)`` — return the persisted plan JSON, cached by
  (path, mtime). Missing file returns ``None``, never raises.
- ``get_field(plan, entity_name, column_name)`` — returns the plan-declared
  field dict for that column, matched case-insensitively across ``entities``
  (dict flavour) and ``data_models`` (list flavour). Returns ``None`` when
  no match — callers MUST fall back to their existing derivation.
- ``get_enum_values(plan, entity_name, column_name)`` — the value list an
  enum Select should use. ``None`` = "plan is silent, use fallback."
- ``get_fk(plan, entity_name, column_name)`` — the FK target ``{table, column}``.
- ``get_semantic_type(plan, entity_name, column_name)`` — control-hint tag.
- ``get_not_null(plan, entity_name, column_name)`` — boolean or None if
  ambiguous.

Every getter is a pure function. Callers pass in the plan (loaded once by
the caller if they want to answer many questions) rather than re-loading.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Load — one shared cache across the whole process, keyed by mtime
# ────────────────────────────────────────────────────────────────────

_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}


def load_plan(output_dir: str | Path) -> dict[str, Any] | None:
    """Return the persisted plan JSON, or ``None`` if unavailable.

    Cached by (path, mtime) so repeated calls across a single post-generate
    pass don't re-parse the file each time.
    """
    path = Path(output_dir) / "src" / "contracts" / "plan.json"
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("[plan-lookup] stat failed for %s: %s", path, exc)
        return None

    key = str(path)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(plan, dict):
            plan = None
    except Exception as exc:  # noqa: BLE001
        log.warning("[plan-lookup] parse failed for %s: %s", path, exc)
        plan = None

    _CACHE[key] = (mtime, plan)
    return plan


# ────────────────────────────────────────────────────────────────────
# Entity/field lookup — normalize the two plan shapes
# ────────────────────────────────────────────────────────────────────

def _iter_entities(plan: dict[str, Any] | None):
    """Yield ``(name, entity_dict)`` across both plan flavours.

    Handles ``entities: {Name: {...}}`` (oneshot) and
    ``data_models: [{name, ...}]`` / ``dataModels`` (full-mode).
    """
    if not isinstance(plan, dict):
        return
    ents = plan.get("entities")
    if isinstance(ents, dict):
        for name, ent in ents.items():
            if isinstance(name, str) and isinstance(ent, dict):
                yield name, ent
    dm = plan.get("data_models") or plan.get("dataModels")
    if isinstance(dm, list):
        for ent in dm:
            if isinstance(ent, dict):
                name = ent.get("name")
                if isinstance(name, str):
                    yield name, ent


def _fold(s: str | None) -> str:
    return (s or "").strip().lower()


def get_entity(plan: dict[str, Any] | None, entity_name: str) -> dict[str, Any] | None:
    """Return the plan entity by name (case-insensitive)."""
    target = _fold(entity_name)
    if not target:
        return None
    for name, ent in _iter_entities(plan):
        if _fold(name) == target:
            return ent
    return None


def get_field(
    plan: dict[str, Any] | None,
    entity_name: str,
    column_name: str,
) -> dict[str, Any] | None:
    """Return the plan-declared field dict for entity.column.

    Match is case-insensitive and tolerant of camelCase vs snake_case:
    ``basedAt`` and ``based_at`` are considered the same column, because
    the DB emitter may write one form and the plan may use the other.
    """
    ent = get_entity(plan, entity_name)
    if not ent:
        return None
    fields = ent.get("fields")
    if not isinstance(fields, list):
        return None
    target = _fold_column(column_name)
    for f in fields:
        if isinstance(f, dict):
            name = f.get("name") or f.get("column")
            if isinstance(name, str) and _fold_column(name) == target:
                return f
    return None


def _fold_column(name: str) -> str:
    """Normalize a column name for equality: lowercase, strip underscores.

    ``basedAt`` → ``basedat``; ``based_at`` → ``basedat``; ``BASED_AT`` →
    ``basedat``. Keeps the comparison forgiving without deep case-analysis.
    """
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


# ────────────────────────────────────────────────────────────────────
# Getters — one per question the pipeline asks
# ────────────────────────────────────────────────────────────────────

import re


def title_case_key(key: str) -> str:
    """Return a human-friendly label for an enum key.

    Spec B1 fallback: when the plan emits a bare `[str]` enum_values
    list, each string is auto-labeled via Title Case so dropdowns don't
    show `ach` and `in_progress` — they show `ACH` (via the caller's
    label override) or `In Progress`.

    - `in_progress` / `credit-card` → `In Progress` / `Credit Card`
    - `inProgress` → `In Progress` (camelCase splits on the boundary)
    - `open` → `Open`
    - empty → empty
    """
    if not key:
        return ""
    # split camelCase into "camel Case"
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key)
    # split on separators
    parts = re.split(r"[\s_\-]+", spaced)
    return " ".join(p[:1].upper() + p[1:] for p in parts if p)


def _extract_enum_key(entry: Any) -> str | None:
    """Return the raw key for one enum_values entry, or None if unrecognizable.

    Accepts bare strings and `{key,...}` / `{value,...}` dicts. The plan
    may emit either shape; the reader normalizes here so callers don't
    branch.
    """
    if isinstance(entry, str):
        v = entry.strip()
        return v or None
    if isinstance(entry, dict):
        raw = entry.get("key") or entry.get("value")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _field_enum_values(f: dict[str, Any]) -> Any:
    """Read a field's enum list from either spelling the planner emits.

    Top-level ``enum_values`` is the canonical shape; some planner
    outputs nest it as ``semantic: {control: "Select", enum_values:
    [...]}`` (seen live on atb0m97x Document.status). Both are the
    plan speaking — honor either, top-level winning.
    """
    vals = f.get("enum_values")
    if isinstance(vals, list) and vals:
        return vals
    sem = f.get("semantic")
    if isinstance(sem, dict):
        return sem.get("enum_values")
    return vals


def get_enum_values(
    plan: dict[str, Any] | None,
    entity_name: str,
    column_name: str,
) -> list[str] | None:
    """Return the plan-declared enum keys for a column, or ``None``.

    ``None`` means "plan is silent" — the caller MUST fall back to its
    existing derivation. An empty list ``[]`` is treated the same as
    None so a mis-emitted empty declaration doesn't produce an empty
    dropdown; callers explicitly opt in to using the plan's list only
    when the list has content.

    Accepts BOTH input shapes (Spec B1):
      - flat strings: ``["open", "closed"]``
      - object form: ``[{key:"open", label:"Open"}, ...]`` /
        ``[{value:"open", label:"Open"}]``

    Return type stays ``list[str]`` (keys only) for back-compat.
    """
    f = get_field(plan, entity_name, column_name)
    if not f:
        return None
    vals = _field_enum_values(f)
    if not isinstance(vals, list) or not vals:
        return None
    out: list[str] = []
    for v in vals:
        key = _extract_enum_key(v)
        if key:
            out.append(key)
    return out or None


def get_enum_options(
    plan: dict[str, Any] | None,
    entity_name: str,
    column_name: str,
) -> list[dict[str, str]] | None:
    """Return the plan-declared enum options as ``[{value, label}]``.

    Spec B1 — the reader that Selects, StatusPicker, and any dropdown-
    emitting scaffolder should call so end-users never see raw enum
    keys like ``ach`` or ``in_progress``.

    Precedence per entry:
      1. dict with ``label`` → use it verbatim (planner's authored label).
      2. dict with only key/value → Title-Case the key.
      3. bare string → Title-Case it.
    """
    f = get_field(plan, entity_name, column_name)
    if not f:
        return None
    vals = _field_enum_values(f)
    if not isinstance(vals, list) or not vals:
        return None
    out: list[dict[str, str]] = []
    for entry in vals:
        key = _extract_enum_key(entry)
        if not key:
            continue
        label: str | None = None
        if isinstance(entry, dict):
            lab = entry.get("label")
            if isinstance(lab, str) and lab.strip():
                label = lab.strip()
        if label is None:
            label = title_case_key(key)
        out.append({"value": key, "label": label})
    return out or None


def get_fk(
    plan: dict[str, Any] | None,
    entity_name: str,
    column_name: str,
) -> dict[str, str] | None:
    """Return ``{"table": ..., "column": ...}`` for the FK target, or None."""
    f = get_field(plan, entity_name, column_name)
    if not f:
        return None
    fk = f.get("fk")
    if not isinstance(fk, dict):
        return None
    table = fk.get("table")
    col = fk.get("column")
    if isinstance(table, str) and isinstance(col, str) and table and col:
        return {"table": table, "column": col}
    return None


def get_semantic_type(
    plan: dict[str, Any] | None,
    entity_name: str,
    column_name: str,
) -> str | None:
    """Return the plan-declared ``semantic_type`` (e.g. "city", "cv-file")."""
    f = get_field(plan, entity_name, column_name)
    if not f:
        return None
    st = f.get("semantic_type")
    return st if isinstance(st, str) and st.strip() else None


def get_lifecycle_status(
    plan: dict[str, Any] | None,
    entity_name: str,
    column_name: str,
) -> bool:
    """Return True if this column is a workflow-state enum (e.g. `status`
    on Ticket goes open→in_progress→closed), False otherwise.

    Spec B7: distinct from lifecycle *At timestamps. A ``lifecycle_status``
    column is:
      - system-managed on create (form scaffolder hides it, uses default_value)
      - user-editable on edit (renders as SegmentedControl / status picker,
        not a bare Select)

    Never fall back to name heuristics — `status` in one domain (kanban card)
    is different from `status` in another (invoice line). The planner decides.
    """
    f = get_field(plan, entity_name, column_name)
    if not f:
        return False
    return bool(f.get("lifecycle_status"))


def get_default_value(
    plan: dict[str, Any] | None,
    entity_name: str,
    column_name: str,
) -> str | None:
    """Return the plan-declared ``default_value`` (or ``default``), or None.

    Spec B7: on lifecycle_status columns, this is the value the create-form
    uses to seed the hidden column (usually the first enum entry, but the
    planner may pick per-domain: a ticket defaults ``open``, a payment
    ``pending``).
    """
    f = get_field(plan, entity_name, column_name)
    if not f:
        return None
    d = f.get("default_value")
    if d is None:
        d = f.get("default")
    if isinstance(d, (str, int, float, bool)):
        s = str(d).strip()
        return s or None
    return None


def get_not_null(
    plan: dict[str, Any] | None,
    entity_name: str,
    column_name: str,
) -> bool | None:
    """Return True if the plan declares NOT NULL, False if nullable, None if unspecified."""
    f = get_field(plan, entity_name, column_name)
    if not f:
        return None
    if "not_null" in f:
        return bool(f["not_null"])
    if "nullable" in f:
        return not bool(f["nullable"])
    return None
