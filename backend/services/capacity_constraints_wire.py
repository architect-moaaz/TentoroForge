"""Materialize ``plan['capacity_constraints']`` into workflow guards.

The fourth primitive in the wire-pass pattern. Turns a declaration
that "no more than N Xs may exist per scope-field value" into a
``capacity_check`` step inserted right before every ``db_insert``
that targets a tracked entity — the step counts existing rows and
short-circuits the workflow (routes to end) when the limit would be
exceeded.

The count-and-branch semantics rely on the workflow runtime's
existing gateway node type; no new runtime primitive required. The
concrete SQL executed by ``capacity_check`` is a follow-up slice
(this pass writes the declaration into the workflow schema; the
runtime picks it up from there).

Plan slot
---------
::

    "capacity_constraints": [
        {"entity": "Application", "scope_field": "recruitment_drive_id",
         "limit": 100, "message": "Drive is full"},
        {"entity": "InterviewSlot", "scope_field": "slot_time",
         "limit": 1},
    ]

Fields:
  * ``entity`` (required)
  * ``scope_field`` (required): the FK / grouping column that defines
    the "per-X" scope for the limit.
  * ``limit`` (required): positive integer.
  * ``message`` (optional): user-facing string surfaced when the
    check fails.
"""
from __future__ import annotations

import copy
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def is_capacity_constraints_enabled() -> bool:
    return os.getenv("FORGE_CAPACITY_CONSTRAINTS", "").lower() in (
        "1", "true", "yes", "on",
    )


def wire_capacity_constraints(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a new plan with capacity-check steps inserted before every
    tracked db_insert.

    No-op when the plan has no ``capacity_constraints`` slot. Never
    mutates input. Never raises.
    """
    if not isinstance(plan, dict):
        return plan
    declarations = _read_declarations(plan)
    if not declarations:
        return dict(plan)

    tracked = {d["entity"]: d for d in declarations}
    new_plan = copy.deepcopy(plan)
    _inject_capacity_checks(new_plan, tracked)
    return new_plan


# ────────────────────────────────────────────────────────────
# Declaration normalization
# ────────────────────────────────────────────────────────────

def _read_declarations(plan: dict) -> list[dict]:
    raw = plan.get("capacity_constraints")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity")
        scope = item.get("scope_field")
        limit = item.get("limit")
        if not (isinstance(entity, str) and entity.strip()):
            continue
        if not (isinstance(scope, str) and scope.strip()):
            continue
        if not isinstance(limit, int) or limit <= 0:
            continue
        message = item.get("message") if isinstance(item.get("message"), str) else None
        out.append({
            "entity":      entity.strip(),
            "scope_field": scope.strip(),
            "limit":       limit,
            "message":     message or f"{entity} is at capacity",
        })
    return out


# ────────────────────────────────────────────────────────────
# Workflow injection
# ────────────────────────────────────────────────────────────

def _inject_capacity_checks(plan: dict, tracked: dict[str, dict]) -> None:
    """Insert a ``capacity_check`` gateway step before every db_insert
    that targets a tracked entity.

    The inserted step:
      * counts rows in ``entity`` where ``scope_field`` matches the
        insert's payload
      * on ``pass`` continues to the original db_insert
      * on ``fail`` routes directly to the end node with an error
        message the caller surfaces

    Idempotency: a step with the same id (``capacity_check_<entity>``)
    is not re-added on a second pass.
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

        end_id = _find_end_id(steps)
        if not end_id:
            continue

        existing_check_ids = {
            step.get("id") for step in steps
            if isinstance(step, dict)
            and str(step.get("id") or "").startswith("capacity_check_")
        }

        # Walk steps and insert a check node before each tracked
        # db_insert. Because we're re-linking predecessors' ``next``,
        # we build a list of insertions and apply them in a second pass.
        insertions: list[tuple[int, dict, str]] = []  # (idx, new_step, insert_target_id)
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            if str(step.get("type") or "") != "db_insert":
                continue
            entity = _step_target_entity(step)
            if not entity or entity not in tracked:
                continue
            check_id = f"capacity_check_{entity}"
            if check_id in existing_check_ids:
                continue
            decl = tracked[entity]
            check_step = _build_capacity_check_step(
                check_id, decl, insert_target=step.get("id") or "",
                fail_target=end_id,
            )
            insertions.append((idx, check_step, step.get("id") or ""))

        if not insertions:
            continue

        # Apply insertions high-index-first so earlier indices don't shift.
        for idx, check_step, insert_target_id in reversed(insertions):
            steps.insert(idx, check_step)
            # Re-link predecessors that pointed at the insert step to
            # point at the check step instead. Preserves the original
            # graph shape modulo the new check node.
            for other in steps:
                if not isinstance(other, dict) or other is check_step:
                    continue
                nxt = other.get("next")
                if nxt == insert_target_id:
                    other["next"] = check_step["id"]


def _step_target_entity(step: dict) -> str | None:
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


def _find_end_id(steps: list) -> str | None:
    for s in steps:
        if isinstance(s, dict) and s.get("type") == "end":
            eid = s.get("id")
            if isinstance(eid, str) and eid.strip():
                return eid
    return None


def _build_capacity_check_step(
    step_id: str,
    decl: dict,
    *,
    insert_target: str,
    fail_target: str,
) -> dict:
    return {
        "id":    step_id,
        "type":  "capacity_check",
        "entity": decl["entity"],
        "config": {
            "entity":      decl["entity"],
            "scope_field": decl["scope_field"],
            "limit":       decl["limit"],
            "message":     decl["message"],
        },
        # Gateway shape — on pass proceed to the original insert; on
        # fail short-circuit to the workflow's end node with the
        # user-facing message.
        "on_pass": insert_target,
        "on_fail": fail_target,
        "next":    insert_target,
    }
