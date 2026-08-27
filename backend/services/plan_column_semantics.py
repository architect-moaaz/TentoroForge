"""Shared plan-reader for per-column semantic hints.

Spec D W2 — this is the single reader every classifier (semantic_field_types,
fk_semantics, and their downstream callers) checks BEFORE falling back to a
regex/name heuristic. When the planner has already authored what a column
means (control kind, FK role, enum vocabulary), the classifier stays out of
its way — the plan wins, verbatim.

The helpers:

  - :func:`get_semantic(plan, entity, column) -> str | None`
      The planner's control hint for a form field. Reads
      ``fields[].semantic.control`` first (the Spec D W2 blob shape),
      then falls back to the legacy per-field ``semantic_type`` string.
      ``None`` means "plan is silent" — the caller MUST run its own
      derivation (`resolve_control` / `_decide`).

  - :func:`get_fk_role(plan, entity, column) -> str | None`
      The planner's FK role for a column (``actor`` | ``assignment`` |
      ``tenancy`` | ``domain``). Reads ``fields[].role`` verbatim; any
      value not in the closed set is treated as ``None`` so a misspelled
      or legacy string can't leak past ``fk_semantics.classify_entity_fks``.

  - :func:`get_enum_values(plan, entity, column) -> list[str] | None`
      The planner's enum vocabulary for a column. Reads
      ``fields[].semantic.enum_values`` first (Spec D W2 blob), then
      falls back to the top-level ``fields[].enum_values`` (Spec B1 shape).
      Empty lists collapse to ``None`` — a dropdown must never render
      empty because the plan mis-emitted ``[]``.

Every helper is a pure function on the already-loaded plan dict. Nothing
raises; a missing/malformed path returns ``None``. Delegates entity/field
lookup to :mod:`services.plan_field_lookup` so the two readers stay in
lock-step on the (case-insensitive, camel/snake-tolerant) name matching
rules — no chance of one classifier finding a field the other misses.
"""
from __future__ import annotations

from typing import Any

from services.plan_field_lookup import (
    get_enum_values as _pfl_get_enum_values,
    get_field as _pfl_get_field,
    get_semantic_type as _pfl_get_semantic_type,
)

# Closed set of valid planner-authored FK roles. Kept in lock-step with
# ``fk_semantics._VALID_PLANNER_ROLES``; anything else is treated as
# "plan is silent" and the name-regex classifier runs.
_VALID_FK_ROLES: frozenset[str] = frozenset({"actor", "assignment", "tenancy", "domain"})


def get_semantic(
    plan: dict[str, Any] | None,
    entity: str | None,
    column: str | None,
) -> str | None:
    """Return the planner's control hint for a column, or ``None``.

    Precedence (Spec D W2 shape wins):
      1. ``fields[].semantic.control`` — the Spec D W2 blob's control key.
      2. ``fields[].semantic_type``    — the legacy per-field string
         (currency / percent / email / phone / multiline / city / cv-file …).

    Callers use this as: "did the planner tell us what control this
    column needs? If yes, respect it; otherwise fall through to
    ``resolve_control`` / ``_decide``." Returns a non-empty stripped
    string, or ``None`` when the plan is silent.
    """
    if not plan or not entity or not column:
        return None
    f = _pfl_get_field(plan, entity, column)
    if not isinstance(f, dict):
        return None
    sem = f.get("semantic")
    if isinstance(sem, dict):
        ctrl = sem.get("control")
        if isinstance(ctrl, str) and ctrl.strip():
            return ctrl.strip()
    # Legacy per-field semantic_type (pre-Spec-D W2 shape).
    return _pfl_get_semantic_type(plan, entity, column)


def get_fk_role(
    plan: dict[str, Any] | None,
    entity: str | None,
    column: str | None,
) -> str | None:
    """Return the planner-authored FK role for a column, or ``None``.

    Only the closed set (``actor`` | ``assignment`` | ``tenancy`` |
    ``domain``) is honored — a misspelled or legacy string collapses to
    ``None`` so ``fk_semantics.classify_entity_fks`` runs its name-regex
    fallback and never emits a garbage role.

    ``None`` = plan is silent — the caller MUST fall back to its
    existing FK-role derivation (registry FK target, name regex).
    """
    if not plan or not entity or not column:
        return None
    f = _pfl_get_field(plan, entity, column)
    if not isinstance(f, dict):
        return None
    role = f.get("role")
    if isinstance(role, str) and role in _VALID_FK_ROLES:
        return role
    return None


def get_enum_values(
    plan: dict[str, Any] | None,
    entity: str | None,
    column: str | None,
) -> list[str] | None:
    """Return the planner-authored enum vocabulary for a column, or ``None``.

    Precedence:
      1. ``fields[].semantic.enum_values`` — the Spec D W2 blob's list.
      2. ``fields[].enum_values``          — the pre-existing Spec B1
         list (both flat strings and ``{key,label}`` dicts, normalised
         through :mod:`services.plan_field_lookup`).

    Empty lists collapse to ``None`` — a dropdown must never render
    empty because the plan mis-emitted ``[]``. Callers use this as: "if
    the planner supplied the vocabulary, that's the authority; otherwise
    fall through to the harvest chain (registry enum_values → seed-plan
    faker → workflow-status literals)."
    """
    if not plan or not entity or not column:
        return None
    f = _pfl_get_field(plan, entity, column)
    if isinstance(f, dict):
        sem = f.get("semantic")
        if isinstance(sem, dict):
            sev = sem.get("enum_values")
            if isinstance(sev, list) and sev:
                out: list[str] = []
                for v in sev:
                    s = str(v).strip() if v not in (None, "") else ""
                    if s and s not in out:
                        out.append(s)
                if out:
                    return out
    # Fall back to plan_field_lookup's Spec B1 reader (handles bare-string
    # and `{key,label}` shapes uniformly).
    return _pfl_get_enum_values(plan, entity, column)
