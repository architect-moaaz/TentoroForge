"""Materialize ``plan['immutability']`` into concrete plan shape.

The second primitive in the wire-pass pattern (see
:mod:`services.audit_trail_wire` for the pilot). Given a declaration
that certain entities become read-only after some lifecycle event,
this pass:

  1. Adds ``is_locked`` (bool) + ``locked_at`` (timestamp) columns to
     each tracked entity.
  2. Annotates each tracked entity's detail page with an
     ``immutability`` metadata block that downstream builders read to
     hide Edit/Delete buttons.
  3. Annotates every ``db_update`` / ``db_delete`` step targeting a
     tracked entity with ``guarded_by: "immutability"`` so the runtime
     can refuse the write when ``is_locked`` is true.

Runtime *enforcement* (the data-engine refusing writes when the guard
metadata is present) is a follow-up slice. This pass is the
declaration + schema materialization only.

Plan slot
---------
::

    "immutability": [
        {"entity": "Feedback", "when": "after_submit",
         "exception_roles": ["admin"]},
    ]

Fields:
  * ``entity`` (required): the tracked entity name.
  * ``when`` (optional): lifecycle trigger — ``after_submit`` |
    ``after_approval`` | ``always``. Materialized as metadata only.
  * ``exception_roles`` (optional): roles that CAN still edit/delete.

Malformed entries are silently dropped.
"""
from __future__ import annotations

import copy
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


_MUTATION_STEP_TYPES = ("db_update", "db_delete")
_VALID_WHEN = ("after_submit", "after_approval", "always")


def is_immutability_enabled() -> bool:
    return os.getenv("FORGE_IMMUTABILITY", "").lower() in (
        "1", "true", "yes", "on",
    )


def wire_immutability(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a new plan with immutability declarations materialized.

    No-op (shallow-copy return) when the plan does not declare any
    immutability entries. Never mutates input. Never raises.
    """
    if not isinstance(plan, dict):
        return plan
    declarations = _read_declarations(plan)
    if not declarations:
        return dict(plan)

    tracked = {d["entity"]: d for d in declarations}
    new_plan = copy.deepcopy(plan)

    _add_lock_columns(new_plan, tracked)
    _annotate_detail_pages(new_plan, tracked)
    _annotate_mutation_steps(new_plan, tracked)

    return new_plan


# ────────────────────────────────────────────────────────────
# Declaration normalization
# ────────────────────────────────────────────────────────────

def _read_declarations(plan: dict) -> list[dict]:
    raw = plan.get("immutability")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity")
        if not (isinstance(entity, str) and entity.strip()):
            continue
        when_raw = str(item.get("when") or "after_submit").strip().lower()
        when = when_raw if when_raw in _VALID_WHEN else "after_submit"
        excs_raw = item.get("exception_roles") or []
        excs = [r for r in excs_raw if isinstance(r, str) and r.strip()] \
            if isinstance(excs_raw, list) else []
        out.append({
            "entity":          entity.strip(),
            "when":            when,
            "exception_roles": excs,
        })
    return out


# ────────────────────────────────────────────────────────────
# Column addition
# ────────────────────────────────────────────────────────────

def _entities_key(plan: dict) -> str:
    if "data_models" in plan:
        return "data_models"
    if "dataModels" in plan:
        return "dataModels"
    return "entities"


def _add_lock_columns(plan: dict, tracked: dict[str, dict]) -> None:
    """Ensure ``is_locked`` + ``locked_at`` columns on each tracked entity.

    Idempotent — re-running never duplicates a column. If the entity
    isn't in the plan we skip it silently rather than inventing one
    (that's a different primitive)."""
    key = _entities_key(plan)
    ents = plan.get(key)
    if not isinstance(ents, list):
        return

    for ent in ents:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name") or ent.get("entity") or "")
        if name not in tracked:
            continue
        fields = ent.get("fields")
        if not isinstance(fields, list):
            fields = []
            ent["fields"] = fields
        existing = {str(f.get("name") or "") for f in fields
                    if isinstance(f, dict)}
        if "is_locked" not in existing:
            fields.append({
                "name":     "is_locked",
                "type":     "boolean",
                "nullable": False,
                "default":  False,
            })
        if "locked_at" not in existing:
            fields.append({
                "name":     "locked_at",
                "type":     "timestamp",
                "nullable": True,
            })


# ────────────────────────────────────────────────────────────
# Detail-page annotation
# ────────────────────────────────────────────────────────────

def _annotate_detail_pages(plan: dict, tracked: dict[str, dict]) -> None:
    """Attach an ``immutability`` metadata block to every detail page
    whose entity is tracked. Downstream detail-page builders read this
    to suppress Edit/Delete buttons unless the viewer's role is listed
    in ``exception_roles``."""
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return
    for p in pages:
        if not isinstance(p, dict):
            continue
        arch = str(p.get("archetype") or "").strip().lower()
        if arch != "detail":
            continue
        ent = str(p.get("entity") or "")
        if ent not in tracked:
            continue
        decl = tracked[ent]
        p["immutability"] = {
            "when":            decl["when"],
            "exception_roles": list(decl["exception_roles"]),
        }


# ────────────────────────────────────────────────────────────
# Workflow step annotation
# ────────────────────────────────────────────────────────────

def _annotate_mutation_steps(plan: dict, tracked: dict[str, dict]) -> None:
    """Attach ``guarded_by: 'immutability'`` metadata to every
    ``db_update`` / ``db_delete`` step that targets a tracked entity.

    The runtime data-engine will (in a follow-up slice) read this
    metadata and refuse the write when the target row has
    ``is_locked = true`` and the caller's role is not in the
    entity's exception_roles list."""
    workflows = plan.get("workflows")
    if not isinstance(workflows, list):
        return
    for w in workflows:
        if not isinstance(w, dict):
            continue
        steps = w.get("steps") or w.get("nodes")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            stype = str(step.get("type") or "")
            if stype not in _MUTATION_STEP_TYPES:
                continue
            entity = _step_target_entity(step)
            if not entity or entity not in tracked:
                continue
            decl = tracked[entity]
            step["guarded_by"] = "immutability"
            step["guard_config"] = {
                "when":            decl["when"],
                "exception_roles": list(decl["exception_roles"]),
            }


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
