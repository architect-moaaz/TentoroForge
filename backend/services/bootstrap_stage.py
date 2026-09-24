"""The legacy generation pipeline's bootstrap stage: discovery, planning, hand-off.

Lifted unchanged out of `smith_architect_wire` when that module — the old
chat front door — was deleted. This never was the front door: it decides
which generation stage a message on the legacy `/generate` path runs, from
state and approval signals, and narrates it. Smith v4 owns the chat turn;
the build pipeline is still driven from here for applications made the old way.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass as _dc_dataclass
from typing import Any
from services.smith_blueprint import Blueprint
from services.smith_blueprint_context import blueprint_to_context


logger = logging.getLogger(__name__)


class BootstrapStageResult:
    """Result of running one bootstrap stage."""
    stage: str            # "discovery" | "planning" | "generation" | "await_approval" | "not_enabled"
    narrator: str = ""    # Smith's architect-voice summary
    dossier: dict | None = None    # populated when stage == "discovery"
    plan: dict | None = None       # populated when stage == "planning"
    error: str | None = None


async def run_bootstrap_stage(
    *,
    project_id: str,
    output_dir: str,
    user_message: str,
    is_discovery_approve: bool,
    is_plan_approve: bool,
    pending_dossier: dict | None,
    org_context: str | None = None,
    domain_context: dict | None = None,
    emit_fn: Any = None,
) -> BootstrapStageResult:
    """One bootstrap stage: discovery, planning, or hand-off to generator.

    Deterministic decision from state + approval signals:

      * No dossier saved AND no approval signal ⇒ run DISCOVERY.
        (Phase B `orchestrate_discovery` + Phase A `record_discovery`.)

      * `[APPROVE_DISCOVERY]` + saved dossier ⇒ run PLANNING.
        (Phase B `orchestrate_planner` + Phase A `record_plan`.)

      * `[APPROVE_PLAN]` ⇒ return stage="generation". The caller
        keeps running the existing generation pipeline — Smith
        doesn't own the build itself; he just narrates before and
        after. Blueprint's ``record_generation_complete`` fires at
        the pipeline's existing completion site (Phase A wiring).

    Never raises — all errors surface via ``result.error`` so the
    caller can fall back to the tactical path."""
    from services.blueprint_pipeline_hooks import record_discovery, record_plan
    from services.smith_narrator import narrate

    try:
        # Stage: hand-off to generation (caller runs existing pipeline)
        if is_plan_approve:
            bp = _load_blueprint_safe(project_id, output_dir)
            prose = narrate(
                stage="generation_handoff",
                fallback=(
                    "Ready to build. Handing off to the generation pipeline — "
                    "I'll narrate as pages, workflows, and schemas materialize."
                ),
                blueprint_context=_blueprint_slice_or_empty(bp),
                user_ask=user_message,
            )
            return BootstrapStageResult(
                stage="generation", narrator=prose,
            )

        # Stage: planning
        if is_discovery_approve and pending_dossier:
            # Bootstrap parity with the classic discover→convert path
            # (JT-T4 extension): synthesise a StructuredBrief from the
            # dossier + user prompt, then prepend the AUTHORITATIVE INPUTS
            # block to the planner's description. The bootstrap flow never
            # creates a DiscoverySession row, so the produce_plan-side
            # brief_lookup returns nothing here — this is the ONLY chance
            # for the bootstrap path to feed the authoritative contract
            # into the planner. On failure we just fall through to the
            # legacy prompt (no regression).
            _description = str(pending_dossier.get("user_prompt") or user_message)
            # Predeclare so a transform_discovery failure below still leaves
            # ``_bootstrap_brief`` bound when we pass it to orchestrate_planner.
            _bootstrap_brief = None
            try:
                from services.discovery_transformer import transform_discovery
                from services.planner_input_render import render_authoritative_block
                _bootstrap_brief = await transform_discovery({
                    "overview":       pending_dossier.get("summary")
                                       or pending_dossier.get("user_prompt")
                                       or user_message,
                    "domain":         pending_dossier.get("domain") or "",
                    "user_prompt":    pending_dossier.get("user_prompt") or user_message,
                    "dossier":        pending_dossier,
                })
                _block = render_authoritative_block(_bootstrap_brief)
                if _block:
                    _description = f"{_block}\n\n{_description}"
                    logger.info(
                        "[bootstrap-plan] injected AUTHORITATIVE INPUTS "
                        "block (%d actors, %d journeys)",
                        len(_bootstrap_brief.actors),
                        len(_bootstrap_brief.user_journeys),
                    )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[bootstrap-plan] transformer / render failed — "
                    "falling back to legacy description"
                )
            planner_art = await orchestrate_planner(
                description=_description,
                domain_context=domain_context or pending_dossier,
                emit_fn=emit_fn,
                output_dir=output_dir,
                structured_brief=_bootstrap_brief,
            )
            # Blueprint hook (Phase A) — record the plan as Smith authored it.
            plan_dict = _planner_artifact_to_dict(planner_art)
            record_plan(
                output_dir=output_dir, project_id=project_id,
                plan=plan_dict,
            )
            bp = _load_blueprint_safe(project_id, output_dir)
            prose = narrate(
                stage="planning", artifact=planner_art,
                blueprint_context=_blueprint_slice_or_empty(bp),
                user_ask=str(pending_dossier.get("user_prompt") or user_message),
            )
            return BootstrapStageResult(
                stage="planning", narrator=prose, plan=plan_dict,
            )

        # Stage: discovery (default first step for a fresh project)
        discovery_art = await orchestrate_discovery(
            output_dir=output_dir,
            user_message=user_message,
            org_context=org_context,
        )
        dossier_dict = _discovery_artifact_to_dict(discovery_art, user_message)
        # Blueprint hook (Phase A) — records domain + open_questions.
        record_discovery(
            output_dir=output_dir, project_id=project_id,
            dossier=dossier_dict,
        )
        prose = narrate(
            stage="discovery", artifact=discovery_art, user_ask=user_message,
        )
        return BootstrapStageResult(
            stage="discovery", narrator=prose, dossier=dossier_dict,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("architect: bootstrap stage failed")
        return BootstrapStageResult(
            stage="not_enabled",
            error=f"{type(exc).__name__}: {exc}",
        )


def _discovery_artifact_to_dict(art, user_message: str) -> dict:
    """Convert a DiscoveryArtifact back to the dossier dict shape the
    existing SSE emission + ``_save_pending_discovery`` expect.

    Prefers the raw dossier attached by ``orchestrate_discovery``
    (domain-agent shape: personas, designPatterns, visualLanguage,
    entitySuggestions, complianceNotes, etc.) — that's the format the
    rest of the pipeline already consumes. Falls back to a synthesized
    dict when no raw dossier is present (e.g. in tests)."""
    raw = getattr(art, "_raw_dossier", None)
    if isinstance(raw, dict) and raw:
        d = dict(raw)
        d.setdefault("user_prompt", user_message)
        # domain_name is what the blueprint hook + narrator prompt read.
        # Domain-agent dossiers use `domain`; synthesize the alias for
        # consumers that expect `domain_name`.
        d.setdefault("domain_name", art.domain_name)
        return d

    return {
        "domain_name": art.domain_name,
        "actors": list(art.actors),
        "verbs": list(art.verbs),
        "distinctive_shape": art.distinctive_shape,
        "proposed_entities": [
            {"name": e.name, "why": e.why}
            for e in art.proposed_entities
        ],
        "open_questions": list(art.open_questions),
        "confidence": art.confidence,
        "user_prompt": user_message,
    }


def _load_blueprint_safe(project_id: str, output_dir: str):
    """Load the blueprint or None — never raises. Used by the
    narrator to enrich prose with what already exists."""
    try:
        return Blueprint.load(project_id=project_id, output_dir=output_dir)
    except Exception:  # noqa: BLE001
        return None


def _blueprint_slice_or_empty(bp) -> str:
    """Render a compact blueprint slice for the narrator prompt, or ""
    when the blueprint is missing / empty."""
    if bp is None:
        return ""
    try:
        return blueprint_to_context(bp, budget=1200)
    except Exception:  # noqa: BLE001
        return ""


def _planner_artifact_to_dict(art) -> dict:
    """Convert a PlannerArtifact to the plan dict shape the existing
    pipeline + ``record_plan`` + SSE `plan_ready` + frontend PlanCard
    all expect.

    Prefers the raw plan dict attached by ``orchestrate_planner``
    (full workflow ``steps``, entity ``fields`` with types, page
    ``type``, and everything the tactical pipeline downstream reads).
    Falls back to synthesizing from artifact fields when no raw plan
    is present (older callers, unit tests)."""
    raw = getattr(art, "_raw_plan", None)
    if isinstance(raw, dict) and (raw.get("models") or raw.get("pages") or raw.get("workflows")):
        return raw

    return {
        "models": [
            {
                "name": e.name, "table": e.table, "purpose": e.purpose,
                "fields": [{"name": f} for f in e.key_fields],
                "why": e.why_shaped_this_way,
            }
            for e in art.entities
        ],
        "workflows": [
            {"name": w.name, "purpose": w.purpose,
             "trigger": {"type": w.trigger}, "why": w.why}
            for w in art.workflows
        ],
        "pages": [
            {"route": p.route, "schema_path": p.schema_path, "role": p.role}
            for p in art.pages
        ],
    }
