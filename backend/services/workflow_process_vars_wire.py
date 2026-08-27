"""Backfill each workflow's ``processVariables`` from its declared steps.

Post-planner normalizer. The planner is instructed to declare every
workflow's process variables (see business_logic_agent.py "processVariables"
guidance), but real runs frequently drop the field or leave it empty. Any
missing declarations then cascade into empty pickers in the editor and, at
runtime, references to undeclared vars.

This pass reconciles the truth into the plan itself: for every
``plan.workflows[*]`` we merge whatever the planner authored with what its
own steps reveal (``set_variable``.variableName, promoted output-mappings).
Planner-authored entries always win; the pass never overwrites a declared
type/description with an inferred one. It only *adds* what was missing.

Enabled by default. Set ``FORGE_WF_PROCESS_VARS_WIRE=off`` to disable.
"""
from __future__ import annotations

import copy
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_OFF = {"0", "false", "no", "off"}


def is_workflow_process_vars_enabled() -> bool:
    # Default-on. Only "off"/"0"/etc. disables.
    return os.getenv("FORGE_WF_PROCESS_VARS_WIRE", "on").lower() not in _OFF


def wire_workflow_process_variables(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a plan whose every workflow declares a merged ``processVariables``.

    Idempotent: running twice yields the same list. Malformed workflows are
    left untouched. Never raises.
    """
    if not isinstance(plan, dict):
        return plan
    workflows = plan.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        return plan

    try:
        from services.workflow_process_variables import (
            derive_process_variables,
            strip_source,
        )
    except Exception:  # noqa: BLE001
        logger.exception("[plan-hooks] workflow_process_variables import failed")
        return plan

    new_plan = copy.deepcopy(plan)
    added_total = 0
    touched_workflows = 0
    for wf in new_plan.get("workflows") or []:
        if not isinstance(wf, dict):
            continue
        # Steps carry `config` at top-level for rich planner shape — that's the
        # shape derive_process_variables' _config() falls back to, so we can
        # pass steps directly as if they were nodes.
        steps = wf.get("steps") if isinstance(wf.get("steps"), list) else []
        before = wf.get("processVariables") if isinstance(wf.get("processVariables"), list) else []
        merged = strip_source(derive_process_variables(wf, steps))
        if not merged:
            # Nothing to declare — leave the field alone. An explicit empty
            # list from the planner stays empty (rare but valid for one-node
            # notification-only workflows).
            continue
        wf["processVariables"] = merged
        gained = len(merged) - len(before)
        if gained > 0:
            added_total += gained
            touched_workflows += 1

    if touched_workflows:
        logger.info(
            "[plan-hooks] workflow_process_vars: +%d vars across %d workflow(s)",
            added_total, touched_workflows,
        )
    return new_plan
