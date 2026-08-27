"""Wire the ``plan['audit_trail']`` declaration into concrete plan shape.

Motivation
----------
This is the pilot for the platform-primitive pattern proposed in the
ATS review: instead of teaching the planner every domain requirement,
we let the plan declare an *intent* ("audit these entities on these
actions") and a deterministic pass materializes it by reusing existing
primitives (an entity + a workflow step + a list page). No new runtime
node type, no new component — just re-use.

Plan slot
---------
``plan["audit_trail"]`` is a list of declarations, e.g.::

    "audit_trail": [
        {"entity": "Feedback",
         "on": ["create", "update", "delete"],
         "reason_required": true,
         "retention_days": 365},
        {"entity": "Application",
         "on": ["update", "delete"]},
    ]

Any element missing/invalid is silently dropped so a bad declaration
never fails generation.

What this pass does
-------------------
1. Ensures an ``AuditEntry`` entity exists in the plan with the
   columns audit trails need (id, actor_id, action, entity_type,
   entity_id, before, after, reason, created_at).
2. For every workflow whose steps mutate a tracked entity via
   ``db_insert`` / ``db_update`` / ``db_delete``, appends a
   ``db_insert`` step against ``AuditEntry`` right before the ``end``
   node.
3. Ensures a ``/audit`` list page exists so admins can browse the
   trail (uses the existing list archetype — nothing new to build).

Contract
--------
Idempotent — running twice yields the same plan. Never raises. Pure
function of the input plan (returns a new dict; never mutates the
input). Byte-unchanged when ``plan["audit_trail"]`` is missing or
empty (backwards-compatible for every existing project).

Env gate
--------
Callers should check :func:`is_audit_trail_enabled` before invoking
so the wire pass is opt-in per project. Also off by default.
"""
from __future__ import annotations

import copy
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


_VALID_ACTIONS = ("create", "update", "delete")

# db_* workflow-step types that count as mutations we should audit.
_MUTATION_STEP_TYPES: dict[str, str] = {
    "db_insert": "create",
    "db_update": "update",
    "db_delete": "delete",
}

AUDIT_ENTITY_NAME = "AuditEntry"
AUDIT_TABLE_NAME = "audit_entry"
AUDIT_PAGE_ROUTE = "/audit"


def is_audit_trail_enabled() -> bool:
    """Return True when FORGE_AUDIT_TRAIL is set to a truthy value."""
    return os.getenv("FORGE_AUDIT_TRAIL", "").lower() in (
        "1", "true", "yes", "on",
    )


# ────────────────────────────────────────────────────────────
# Public entry point
# ────────────────────────────────────────────────────────────

def wire_audit_trail(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a new plan with the audit-trail declaration materialized.

    A no-op (returns a shallow copy of the input) when the plan does
    not declare any audit_trail entries. Silent on every error class
    the plan can present — a malformed declaration must never fail
    generation.
    """
    if not isinstance(plan, dict):
        return plan  # nothing sensible we can do

    declarations = _read_declarations(plan)
    if not declarations:
        # No-op fast path: return a shallow copy so callers can safely
        # assume they own the result without worrying about mutation.
        return dict(plan)

    tracked = {d["entity"]: d for d in declarations}
    new_plan = copy.deepcopy(plan)

    _ensure_audit_entity(new_plan)
    _inject_audit_steps_into_workflows(new_plan, tracked)
    _ensure_audit_list_page(new_plan)

    return new_plan


# ────────────────────────────────────────────────────────────
# Declaration normalization
# ────────────────────────────────────────────────────────────

def _read_declarations(plan: dict) -> list[dict]:
    """Extract + normalize ``plan['audit_trail']``.

    Silently drops entries missing an entity name or with no valid
    action. Actions are lower-cased and de-duplicated. Order-preserving
    so downstream logs stay predictable.
    """
    raw = plan.get("audit_trail")
    if not isinstance(raw, list):
        return []

    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity")
        if not (isinstance(entity, str) and entity.strip()):
            continue
        actions_raw = item.get("on") or list(_VALID_ACTIONS)
        if not isinstance(actions_raw, list):
            continue
        actions = []
        seen: set[str] = set()
        for a in actions_raw:
            if not isinstance(a, str):
                continue
            norm = a.strip().lower()
            if norm in _VALID_ACTIONS and norm not in seen:
                actions.append(norm)
                seen.add(norm)
        if not actions:
            continue
        out.append({
            "entity": entity.strip(),
            "on": actions,
            "reason_required": bool(item.get("reason_required", False)),
            "retention_days": item.get("retention_days"),
        })
    return out


# ────────────────────────────────────────────────────────────
# AuditEntry entity
# ────────────────────────────────────────────────────────────

def _ensure_audit_entity(plan: dict) -> None:
    """Add the ``AuditEntry`` entity if the plan doesn't already carry it.

    Plans store entities under one of two keys; we honor whichever is
    already in use and only fall back to ``entities`` on an empty plan.
    Idempotent — a second call is a no-op.
    """
    key = "data_models" if "data_models" in plan else (
        "dataModels" if "dataModels" in plan else "entities"
    )
    ents = plan.get(key)
    if not isinstance(ents, list):
        ents = []
        plan[key] = ents

    for e in ents:
        if isinstance(e, dict) and _entity_name(e) == AUDIT_ENTITY_NAME:
            return  # already present

    ents.append(_build_audit_entity_dict())


def _entity_name(e: dict) -> str:
    return str(e.get("name") or e.get("entity") or "")


def _build_audit_entity_dict() -> dict:
    return {
        "name": AUDIT_ENTITY_NAME,
        "table": AUDIT_TABLE_NAME,
        "description": (
            "Immutable audit log — one row per tracked mutation. "
            "Written by the audit_trail wire pass, never mutated at "
            "runtime."
        ),
        "fields": [
            {"name": "id",          "type": "uuid",      "primary_key": True},
            {"name": "actor_id",    "type": "uuid",      "nullable": True},
            {"name": "action",      "type": "text",      "nullable": False,
             "enum_values": list(_VALID_ACTIONS)},
            {"name": "entity_type", "type": "text",      "nullable": False},
            {"name": "entity_id",   "type": "text",      "nullable": False},
            {"name": "before",      "type": "jsonb",     "nullable": True},
            {"name": "after",       "type": "jsonb",     "nullable": True},
            {"name": "reason",      "type": "text",      "nullable": True},
            {"name": "created_at",  "type": "timestamp", "nullable": False,
             "default": "now()"},
        ],
    }


# ────────────────────────────────────────────────────────────
# Workflow injection
# ────────────────────────────────────────────────────────────

def _inject_audit_steps_into_workflows(
    plan: dict,
    tracked: dict[str, dict],
) -> None:
    """For every workflow that mutates a tracked entity, insert an
    audit-logging ``db_insert`` step right before its ``end`` node.

    Only mutations against tracked entities are audited. A workflow
    that touches an untracked entity is left alone. If the workflow
    doesn't have an ``end`` node we skip it — the pass is defensive,
    never invasive.
    """
    workflows = plan.get("workflows")
    if not isinstance(workflows, list):
        return

    for w in workflows:
        if not isinstance(w, dict):
            continue
        steps = w.get("steps") or w.get("nodes")
        if not isinstance(steps, list):
            continue

        # Find every mutation step for a tracked entity.
        audit_targets: list[tuple[str, str, str]] = []  # (step_id, action, entity)
        for step in steps:
            if not isinstance(step, dict):
                continue
            action = _MUTATION_STEP_TYPES.get(str(step.get("type") or ""))
            if not action:
                continue
            entity = _step_target_entity(step)
            if not entity or entity not in tracked:
                continue
            # Skip when the plan declares the entity but not this action —
            # ``on: ["create"]`` must NOT audit a db_update.
            if action not in (tracked[entity].get("on") or []):
                continue
            audit_targets.append((str(step.get("id") or ""), action, entity))

        if not audit_targets:
            continue

        # Idempotency: if the workflow already has an audit_log step
        # for the exact (action, entity) triple, skip re-adding it.
        existing_audit_ids = {
            step.get("id") for step in steps
            if isinstance(step, dict)
            and str(step.get("id") or "").startswith("audit_log_")
        }

        end_step_idx = next(
            (i for i, s in enumerate(steps)
             if isinstance(s, dict) and s.get("type") == "end"),
            None,
        )
        if end_step_idx is None:
            continue  # defensive — malformed workflow

        for step_id, action, entity in audit_targets:
            new_id = f"audit_log_{action}_{entity}"
            if new_id in existing_audit_ids:
                continue
            audit_step = _build_audit_step(new_id, action, entity, step_id)
            steps.insert(end_step_idx, audit_step)
            end_step_idx += 1  # keep pointing at 'end'
            existing_audit_ids.add(new_id)


def _step_target_entity(step: dict) -> str | None:
    """Extract the entity a mutation step writes to.

    Tolerates the two shapes we see in plans: ``entity`` on the step
    directly, or nested under ``config`` / ``params`` / ``values``.
    """
    for key in ("entity", "table", "target"):
        val = step.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    for container_key in ("config", "params", "values"):
        container = step.get(container_key)
        if isinstance(container, dict):
            for key in ("entity", "table", "target"):
                val = container.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return None


def _build_audit_step(
    step_id: str,
    action: str,
    entity: str,
    source_step_id: str,
) -> dict:
    """Build the db_insert step that logs one mutation into AuditEntry.

    The ``source_step_id`` reference lets the runtime pull the actual
    row id from the preceding mutation's output — resolved at execution
    time by the workflow engine, not by us.
    """
    return {
        "id": step_id,
        "type": "db_insert",
        "entity": AUDIT_ENTITY_NAME,
        "config": {
            "entity": AUDIT_ENTITY_NAME,
            "values": {
                "action":      action,
                "entity_type": entity,
                "entity_id":   f"{{{{steps.{source_step_id}.output.id}}}}",
                "actor_id":    "{{context.actor_id}}",
                "after":       f"{{{{steps.{source_step_id}.output}}}}",
            },
        },
        "next": None,
    }


# ────────────────────────────────────────────────────────────
# /audit list page
# ────────────────────────────────────────────────────────────

def _ensure_audit_list_page(plan: dict) -> None:
    """Add a ``/audit`` list page for admins if the plan doesn't already
    declare one at that route.

    Uses the ``list`` archetype so downstream builders emit a Table +
    filter row from ``AuditEntry`` — no new components required.
    """
    pages = plan.get("pages")
    if not isinstance(pages, list):
        pages = []
        plan["pages"] = pages

    for p in pages:
        if isinstance(p, dict) and p.get("route") == AUDIT_PAGE_ROUTE:
            return

    pages.append({
        "route": AUDIT_PAGE_ROUTE,
        "archetype": "list",
        "entity": AUDIT_ENTITY_NAME,
        "title": "Audit Trail",
        "description": (
            "Every tracked mutation, newest first. Read-only, admin-scoped."
        ),
        "roles": ["admin"],
        "columns": [
            "created_at", "action", "entity_type",
            "entity_id", "actor_id", "reason",
        ],
        "sort": [{"field": "created_at", "dir": "desc"}],
    })
