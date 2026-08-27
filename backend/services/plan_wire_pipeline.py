"""Shared narrative + plan-wire hooks for every planning entry point.

Two orchestration paths call the planner:

  * ``routers.generate.produce_plan`` — the classic path used by
    generate.py's endpoints.
  * ``services.smith_agent_adapters.orchestrate_planner`` — the
    smith-arch path used when ``FORGE_SMITH_ARCHITECT=1`` is set.

Both need to (a) prepend the discovery-narrative expansion to the
planner prompt and (b) run the plan-level primitive wire passes
after each ``run_planner_oneshot`` result. This module owns both
so the two paths can never drift.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def apply_narrative_expansion(
    prompt: str,
    structured_brief: Any = None,
    output_dir: str | Path | None = None,
    emit_fn: Any = None,
) -> str:
    """Return ``prompt`` with the narrative block prepended if narrative
    expansion is enabled and the LLM call succeeds.

    Enablement priority (first hit wins):
      1. **Persisted generation profile** (``<output_dir>/contracts/
         generation-profile.json``) — set at DiscoveryApprove when the
         user picks Fast vs Complete. ``narrative_expansion`` flag rules.
      2. ``FORGE_NARRATIVE_EXPANSION`` env var — the pre-profile default,
         still honored for older projects and command-line runs.

    Persists to ``<output_dir>/contracts/domain-narrative.md`` when
    ``output_dir`` is supplied. Byte-unchanged fall-through when the
    gate is off or the LLM errors."""
    try:
        from services.discovery_narrative import (
            expand_prompt_to_narrative,
            is_narrative_enabled,
            persist_narrative,
            render_narrative_block,
        )
    except Exception:  # noqa: BLE001
        logger.exception("[plan-hooks] discovery_narrative import failed")
        return prompt

    # (1) profile-driven gate — user's explicit Fast/Complete pick wins.
    if output_dir is not None:
        try:
            from services.generation_profile import load_profile
            profile = load_profile(str(output_dir))
            if profile is not None:
                if not profile.narrative_expansion:
                    logger.info(
                        "[plan-hooks] narrative disabled by profile=%s",
                        profile.id,
                    )
                    return prompt
                # profile says ON — skip the env check and proceed
        except Exception:  # noqa: BLE001
            logger.exception("[plan-hooks] profile load failed — falling back to env")

    # (2) env fallback — used when no profile was persisted for this run.
    if not is_narrative_enabled():
        return prompt

    try:
        # structured_brief here can be a StructuredBrief dataclass, a dict,
        # or None. expand_prompt_to_narrative accepts a dict/None; convert
        # once here so callers don't have to.
        brief_dict: dict | None = None
        if structured_brief is not None:
            if isinstance(structured_brief, dict):
                brief_dict = structured_brief
            else:
                for method in ("to_dict", "model_dump", "dict"):
                    fn = getattr(structured_brief, method, None)
                    if callable(fn):
                        try:
                            brief_dict = fn()
                            break
                        except Exception:  # noqa: BLE001
                            continue

        narrative = await expand_prompt_to_narrative(
            prompt, brief_dict, emit_fn=emit_fn,
        )
        if not narrative:
            return prompt

        if output_dir is not None:
            persist_narrative(output_dir, narrative)

        block = render_narrative_block(narrative)
        if not block:
            return prompt
        return f"{block}\n\n{prompt}"
    except Exception:  # noqa: BLE001
        logger.exception(
            "[plan-hooks] narrative expansion failed; using original prompt"
        )
        return prompt


def apply_plan_wires(plan: dict[str, Any]) -> dict[str, Any]:
    """Run every enabled plan-level primitive wire pass in sequence.

    Each pass is independently env-gated (see the ``is_*_enabled``
    functions in each wire module). Each is idempotent. Each swallows
    its own errors so one broken primitive never breaks generation.

    Order is stable so wired plans hash consistently across runs and
    across the two orchestration paths."""
    if not isinstance(plan, dict):
        return plan

    for name, is_enabled, wire in _plan_wire_registry():
        try:
            if is_enabled():
                plan = wire(plan)
        except Exception:  # noqa: BLE001
            logger.exception(
                "[plan-hooks] %s wire failed; keeping previous plan", name
            )
    return plan


def _plan_wire_registry():
    """Lazy imports so a missing wire module in a partial install
    never blocks generation."""
    from services.audit_trail_wire import (
        is_audit_trail_enabled, wire_audit_trail,
    )
    from services.capacity_constraints_wire import (
        is_capacity_constraints_enabled, wire_capacity_constraints,
    )
    from services.field_visibility_wire import (
        is_field_visibility_enabled, wire_field_visibility,
    )
    from services.immutability_wire import (
        is_immutability_enabled, wire_immutability,
    )
    from services.wizard_wire import (
        is_wizard_enabled, wire_wizards,
    )
    from services.workflow_process_vars_wire import (
        is_workflow_process_vars_enabled, wire_workflow_process_variables,
    )
    return [
        ("audit_trail",          is_audit_trail_enabled,          wire_audit_trail),
        ("immutability",         is_immutability_enabled,         wire_immutability),
        ("field_visibility",     is_field_visibility_enabled,     wire_field_visibility),
        ("capacity_constraints", is_capacity_constraints_enabled, wire_capacity_constraints),
        ("wizard",               is_wizard_enabled,               wire_wizards),
        # Runs late so it sees any workflows the wires above added/edited.
        ("workflow_process_vars",
         is_workflow_process_vars_enabled,
         wire_workflow_process_variables),
    ]
