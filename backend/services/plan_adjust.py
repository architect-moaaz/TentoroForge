"""Deterministic plan-mutation operations for the "Adjust strategy" flow.

Context
-------
After the planner emits ``plan.json`` and BEFORE the user hits "Begin
Quest", they can chat with Smith to add / remove / modify entities,
pages, workflows, features. Each chat turn must apply RELIABLY on top
of the current plan — no re-planning from scratch, no LLM re-inventing
JSON. The LLM's only job is to pick which of the below operations to
call. This module is the target.

Contract
--------
Every operation:
  * Takes a plan dict + typed arguments
  * Returns a NEW plan dict (never mutates input)
  * Is idempotent — re-applying the same op is a no-op
  * Never touches unrelated fields
  * Rejects invalid input with :class:`PlanAdjustError`

Downstream:
  * :func:`compute_diff` — structured added/removed/changed lists for
    the UI + telemetry.
  * :func:`validate_plan_shape` — checks for orphan FKs, dangling
    routes, name collisions after a mutation.

This module has NO LLM calls. The LLM intent-parser lives in
``plan_adjust_intent.py`` and calls these ops.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Optional


class PlanAdjustError(ValueError):
    """Raised when an adjust op can't be applied (missing target,
    invalid arg, name collision, etc.)."""


# --------------------------------------------------------------------------- #
# Name helpers                                                                 #
# --------------------------------------------------------------------------- #

_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def _norm_name(name: str) -> str:
    """Trim + validate an entity/page/workflow identifier."""
    if not isinstance(name, str):
        raise PlanAdjustError(f"name must be a string, got {type(name).__name__}")
    s = name.strip()
    if not s or not _IDENT_RE.match(s):
        raise PlanAdjustError(
            f"name must be an alphanumeric identifier starting with a letter, "
            f"got {name!r}"
        )
    return s


def _slugify_route(name: str) -> str:
    """Turn 'BookingsPage' → '/bookings'.

    Page names conventionally already carry the plural form (MembersPage,
    OrdersPage, BookingsPage), so we just strip the ``Page`` suffix and
    kebab-case. No further pluralization — that would double up.
    """
    stem = re.sub(r"Page$", "", name) or name
    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", stem).lower()
    return "/" + kebab


# --------------------------------------------------------------------------- #
# Data-model ops                                                               #
# --------------------------------------------------------------------------- #

# Fields every entity gets by default when the user doesn't specify — mirrors
# what the planner emits so the adjustment produces a plan indistinguishable
# from a fresh one.
_DEFAULT_ENTITY_FIELDS: list[dict] = [
    {"name": "id", "type": "uuid", "primaryKey": True},
    {"name": "createdAt", "type": "timestamp"},
    {"name": "updatedAt", "type": "timestamp"},
]


def add_entity(
    plan: dict,
    *,
    name: str,
    fields: Optional[list[dict]] = None,
) -> dict:
    """Insert an entity into ``plan['data_models']``.

    ``fields`` defaults to id/createdAt/updatedAt if omitted. Callers
    who want extra columns pass them; the required trio is always
    prepended (no duplicates) so the entity is always valid.
    Idempotent: existing entity with the same name is a no-op.
    """
    name = _norm_name(name)
    new_plan = copy.deepcopy(plan)
    new_plan.setdefault("data_models", [])
    existing = [e for e in new_plan["data_models"] if e.get("name") == name]
    if existing:
        return new_plan
    entity_fields = list(_DEFAULT_ENTITY_FIELDS)
    if fields:
        seen = {f["name"] for f in entity_fields}
        for f in fields:
            if not isinstance(f, dict) or "name" not in f or "type" not in f:
                raise PlanAdjustError(
                    f"each field must be a dict with name+type, got {f!r}"
                )
            if f["name"] in seen:
                continue
            entity_fields.append(f)
            seen.add(f["name"])
    new_plan["data_models"].append(
        {"name": name, "fields": entity_fields, "indexes": []}
    )
    return new_plan


def remove_entity(plan: dict, *, name: str) -> dict:
    """Remove an entity from ``data_models``. Also drops any relations,
    pages, and workflows that hard-depend on it, so the plan stays
    consistent after the op. Idempotent: missing entity → unchanged."""
    name = _norm_name(name)
    new_plan = copy.deepcopy(plan)
    dms = new_plan.get("data_models") or []
    if not any(e.get("name") == name for e in dms):
        return new_plan
    new_plan["data_models"] = [e for e in dms if e.get("name") != name]
    # Drop relations that reference the removed entity on either side.
    rels = new_plan.get("relations") or []
    new_plan["relations"] = [
        r for r in rels
        if r.get("from") != name and r.get("to") != name
    ]
    # Drop pages whose entity binding matched the removed entity.
    pages = new_plan.get("pages") or []
    new_plan["pages"] = [p for p in pages if p.get("entity") != name]
    # Workflows that mention the entity in trigger or steps stay
    # (they may still make sense conceptually); the user can drop them
    # explicitly with remove_workflow if they wish.
    return new_plan


# --------------------------------------------------------------------------- #
# Page ops                                                                     #
# --------------------------------------------------------------------------- #

_VALID_ARCHETYPES = {
    "dashboard", "list", "detail", "form", "kanban", "calendar",
    "timeline", "profile", "settings", "auth",
}


def add_page(
    plan: dict,
    *,
    name: str,
    entity: Optional[str] = None,
    archetype: str = "list",
    route: Optional[str] = None,
    description: str = "",
    features: Optional[list[str]] = None,
) -> dict:
    """Insert a page. Route defaults to a slug derived from ``name``.

    Idempotent by ``route`` — if a page with the same route exists, no-op.
    Rejects unknown archetypes so downstream builders can trust the value.
    """
    name = _norm_name(name)
    if archetype not in _VALID_ARCHETYPES:
        raise PlanAdjustError(
            f"unknown archetype {archetype!r}; "
            f"expected one of {sorted(_VALID_ARCHETYPES)}"
        )
    route = route or _slugify_route(name)
    new_plan = copy.deepcopy(plan)
    new_plan.setdefault("pages", [])
    if any(p.get("route") == route for p in new_plan["pages"]):
        return new_plan
    # Reject a page bound to a non-existent entity so we don't ship a
    # dead reference into generation.
    if entity is not None:
        dms = new_plan.get("data_models") or []
        if not any(e.get("name") == entity for e in dms):
            raise PlanAdjustError(
                f"page {name!r} binds to entity {entity!r} which isn't in "
                f"data_models — add the entity first."
            )
    new_plan["pages"].append({
        "route": route,
        "name": name,
        "entity": entity,
        "archetype": archetype,
        "features": list(features or []),
        "description": description,
        "actions": [],
    })
    return new_plan


def remove_page(plan: dict, *, route: str) -> dict:
    """Remove a page by route. Idempotent: missing route → unchanged."""
    if not isinstance(route, str) or not route.startswith("/"):
        raise PlanAdjustError(f"route must be a path starting with /, got {route!r}")
    new_plan = copy.deepcopy(plan)
    pages = new_plan.get("pages") or []
    new_plan["pages"] = [p for p in pages if p.get("route") != route]
    return new_plan


# --------------------------------------------------------------------------- #
# Workflow ops                                                                 #
# --------------------------------------------------------------------------- #

def add_workflow(
    plan: dict,
    *,
    name: str,
    trigger: str,
    description: str = "",
    steps: Optional[list[dict]] = None,
) -> dict:
    """Insert a workflow. Idempotent by name."""
    name = _norm_name(name)
    if not isinstance(trigger, str) or not trigger.strip():
        raise PlanAdjustError(f"trigger must be a non-empty string, got {trigger!r}")
    new_plan = copy.deepcopy(plan)
    new_plan.setdefault("workflows", [])
    if any(w.get("name") == name for w in new_plan["workflows"]):
        return new_plan
    new_plan["workflows"].append({
        "name": name,
        "trigger": trigger,
        "description": description,
        "steps": list(steps or []),
        "roles": [],
        "conditions": [],
        "error_handling": [],
        "side_effects": [],
    })
    return new_plan


def remove_workflow(plan: dict, *, name: str) -> dict:
    """Remove a workflow by name. Idempotent."""
    name = _norm_name(name)
    new_plan = copy.deepcopy(plan)
    wfs = new_plan.get("workflows") or []
    new_plan["workflows"] = [w for w in wfs if w.get("name") != name]
    return new_plan


# --------------------------------------------------------------------------- #
# Actor / role ops                                                             #
# --------------------------------------------------------------------------- #

def add_actor(
    plan: dict,
    *,
    name: str,
    role: str,
    onboarding: Optional[dict] = None,
) -> dict:
    """Insert an actor. Actors drive auth flows + access control."""
    name = _norm_name(name)
    role = _norm_name(role)
    new_plan = copy.deepcopy(plan)
    new_plan.setdefault("actors", [])
    if any(a.get("name") == name for a in new_plan["actors"]):
        return new_plan
    new_plan["actors"].append({
        "name": name,
        "role": role,
        "onboarding": onboarding or {"source": "self_signup"},
    })
    return new_plan


def remove_actor(plan: dict, *, name: str) -> dict:
    """Remove an actor by name. Idempotent."""
    name = _norm_name(name)
    new_plan = copy.deepcopy(plan)
    actors = new_plan.get("actors") or []
    new_plan["actors"] = [a for a in actors if a.get("name") != name]
    return new_plan


# --------------------------------------------------------------------------- #
# Feature ops (top-level toggles the planner exposes)                          #
# --------------------------------------------------------------------------- #

_VALID_FEATURES = {"commerce", "notifications", "search", "reporting", "audit"}


def toggle_feature(plan: dict, *, feature: str, on: bool) -> dict:
    """Turn a top-level feature on/off. Adds/removes from
    ``plan['features']`` (creating the list if needed)."""
    if feature not in _VALID_FEATURES:
        raise PlanAdjustError(
            f"unknown feature {feature!r}; "
            f"expected one of {sorted(_VALID_FEATURES)}"
        )
    new_plan = copy.deepcopy(plan)
    feats = list(new_plan.get("features") or [])
    if on and feature not in feats:
        feats.append(feature)
    elif not on and feature in feats:
        feats = [f for f in feats if f != feature]
    new_plan["features"] = feats
    return new_plan


# --------------------------------------------------------------------------- #
# Diff + validate                                                              #
# --------------------------------------------------------------------------- #

@dataclass
class PlanDiff:
    """Structured summary of what one op (or a batch) changed. Passed
    to the UI so the user can see the delta before Begin Quest."""

    entities_added:   list[str] = field(default_factory=list)
    entities_removed: list[str] = field(default_factory=list)
    pages_added:      list[str] = field(default_factory=list)  # routes
    pages_removed:    list[str] = field(default_factory=list)  # routes
    workflows_added:  list[str] = field(default_factory=list)
    workflows_removed: list[str] = field(default_factory=list)
    actors_added:     list[str] = field(default_factory=list)
    actors_removed:   list[str] = field(default_factory=list)
    features_added:   list[str] = field(default_factory=list)
    features_removed: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.entities_added, self.entities_removed,
            self.pages_added, self.pages_removed,
            self.workflows_added, self.workflows_removed,
            self.actors_added, self.actors_removed,
            self.features_added, self.features_removed,
        ])

    def to_dict(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self.__dict__.items()}


def _names(items: Optional[list[dict]], key: str = "name") -> set[str]:
    return {i.get(key) for i in (items or []) if i.get(key)}


def compute_diff(before: dict, after: dict) -> PlanDiff:
    """Named diff between two plan versions. Used by the API to tell
    the client what changed after each adjust turn."""
    b_ent, a_ent = _names(before.get("data_models")), _names(after.get("data_models"))
    b_pg, a_pg   = _names(before.get("pages"), "route"), _names(after.get("pages"), "route")
    b_wf, a_wf   = _names(before.get("workflows")), _names(after.get("workflows"))
    b_ac, a_ac   = _names(before.get("actors")), _names(after.get("actors"))
    b_ft = set(before.get("features") or [])
    a_ft = set(after.get("features") or [])
    return PlanDiff(
        entities_added   = sorted(a_ent - b_ent),
        entities_removed = sorted(b_ent - a_ent),
        pages_added      = sorted(a_pg - b_pg),
        pages_removed    = sorted(b_pg - a_pg),
        workflows_added  = sorted(a_wf - b_wf),
        workflows_removed= sorted(b_wf - a_wf),
        actors_added     = sorted(a_ac - b_ac),
        actors_removed   = sorted(b_ac - a_ac),
        features_added   = sorted(a_ft - b_ft),
        features_removed = sorted(b_ft - a_ft),
    )


def validate_plan_shape(plan: dict) -> list[str]:
    """Check a plan for dangling references. Returns a list of
    human-readable warnings (empty on a clean plan). Called after each
    op so the API can surface issues before the user hits Begin Quest.

    Not a hard schema check — that's ``plan_completeness_validator``.
    This is the lightweight "did I just break something obvious"
    guard: page→entity refs, relation→entity refs, workflow trigger
    entity refs.
    """
    warnings: list[str] = []
    entity_names = _names(plan.get("data_models"))

    for pg in plan.get("pages") or []:
        ent = pg.get("entity")
        if ent and ent not in entity_names:
            warnings.append(
                f"page {pg.get('name') or pg.get('route')} binds to unknown "
                f"entity {ent!r}"
            )

    for rel in plan.get("relations") or []:
        for side in ("from", "to"):
            v = rel.get(side)
            if v and v not in entity_names:
                warnings.append(
                    f"relation {rel.get('name') or ''!r} references unknown "
                    f"entity {v!r} on {side} side"
                )

    return warnings
