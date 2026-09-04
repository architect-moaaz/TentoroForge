"""What the running backend calls for one Smith turn.

`_handle_smith_turn` in ``routers/generate.py`` invokes
:func:`run_iteration_via_architect` for a change turn and
:func:`run_bootstrap_stage` for a new application. This module's job is to
prepare the context those need and adapt what comes back — it does not decide
anything itself.

  * :func:`run_iteration_via_architect` — ensure the Blueprint exists, build
    the recall + architect context block, and hand the turn to
    ``agents.smith_agent.run_smith_agent``, the ReAct loop that owns it.
  * :func:`run_bootstrap_stage` — discovery and planning for a new app, as
    stages the chat stream can narrate.
  * :func:`turn_result_to_legacy_dict` — the shape the SSE handler expects.

WHAT USED TO BE HERE. Half this file was the form-filler the ReAct loop
replaced: one LLM call (``_understand_ask``) extracting {screen,
element_label, current_behavior, desired_behavior, target_file}, then
``_make_iteration_move`` dispatching to six seams. The loop took over and none
of it was deleted — 500 lines, imported, module-level, and reading to anyone
opening the file as the live path. It cost the better part of an hour to
establish that the understanding it produced was never consulted.

Dead code that LOOKS live is worse than no code, because the next person
debugging a turn reads it first. It is gone; ``git log`` has it.

The seams it dispatched to (edit_page, add_page, add_workflow, add_entity,
edit_file, replan) are all reachable as TOOLS in ``services.smith_tools``,
which is where the loop looks for them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass as _dc_dataclass
from typing import Any

from services.blueprint_backfill import backfill_project_blueprint
from services.smith_agent_adapters import (
    orchestrate_discovery,
    orchestrate_planner,
)
from services.smith_blueprint import Blueprint
from services.smith_blueprint_context import blueprint_to_context
from services.smith_session import TurnResult


logger = logging.getLogger(__name__)



# --------------------------------------------------------------------------- #
# Public entry — the function _handle_smith_turn calls
# --------------------------------------------------------------------------- #

def run_iteration_via_architect(
    message: str, output_dir: str, project_id: str,
    memory_block: str = "",
    *,
    reasoning_callback: Any = None,
    progress_callback: Any = None,
) -> TurnResult:
    """Run one iteration turn as the SMITH ARCHITECT — a ReAct agent
    with real tools (``list_pages``, ``read_page``, ``list_components``,
    ``edit_page``, ``add_page``, ``add_workflow``, ``add_entity``,
    ``run_guards``, ``read_file``, ``edit_file``, ``impact_analysis``,
    ``verify_promise``, ``think``).

    Delegates to :func:`agents.smith_agent.run_smith_agent` — the real
    tool-use loop that ships in the codebase. The architect wire's job
    is to (1) ensure the Blueprint exists (backfilling on first sight),
    (2) augment the recall block with Blueprint + component-catalog
    context so Smith speaks as the architect who authored the app,
    (3) adapt the agent's ``{diagnosis, answer, question, handoff,
    trace, edited_paths}`` result into a ``TurnResult``.

    The prior form-filler shape (one LLM call → structured target →
    dispatch to a seam) was the regression; this restores the ReAct
    loop the S1-S5 tasks originally shipped."""
    # Blueprint precondition: backfill from the registry if missing.
    try:
        backfill_project_blueprint(project_id=project_id, output_dir=output_dir)
    except Exception:  # noqa: BLE001
        logger.exception("architect: blueprint backfill failed — proceeding")

    # Bootstrap detection: only when the output dir itself doesn't
    # exist at all — that's a truly fresh project. If the dir exists
    # (even with no src/ yet — legacy projects, partial builds) the
    # ReAct agent gets to decide: it can inspect, report emptiness,
    # or start planning. Overly-narrow gating here is what turned the
    # architect stack into a form-filler.
    from pathlib import Path as _P
    if not _P(output_dir).exists():
        return TurnResult(
            status="not_enabled",
            answer=(
                "Project directory doesn't exist yet — bootstrap needed."
            ),
        )

    bp = Blueprint.load(project_id=project_id, output_dir=output_dir)

    # Build the recall block (context engine — component contracts +
    # entity contracts + resource registry). ``assemble_recall`` reads
    # the project files directly and returns a prompt-ready block.
    recall_block = ""
    try:
        from services.app_recall import assemble_recall
        recall = assemble_recall(output_dir)
        recall_block = recall.to_prompt_block()
    except Exception:  # noqa: BLE001
        logger.exception("architect: assemble_recall failed — continuing without")

    # Augment with Blueprint slice + Smith-authored-this-app persona so
    # the agent behaves as the architect the vision describes.
    arch_block = _build_architect_context_block(bp)
    if arch_block:
        recall_block = f"{arch_block}\n\n{recall_block}" if recall_block else arch_block

    # Delegate to the real ReAct agent. The caller (``_handle_smith_turn``)
    # builds the DB-persisted smith_memory block and passes it in — the
    # architect needs it so multi-turn conversations don't lose the prior
    # "here's the scope, does that look right?" proposal on the user's
    # "please go ahead" reply.
    try:
        from agents.smith_agent import run_smith_agent
        result = run_smith_agent(
            user_message=message,
            output_dir=output_dir,
            recall_block=recall_block,
            memory_block=memory_block or "",
            # Smith thinking out loud. Both are worker-thread callbacks the
            # SSE stream drains; passing them is the whole difference between
            # a turn the user can watch and a spinner. They were on the
            # agent's signature and nothing on this path supplied them.
            reasoning_callback=reasoning_callback,
            progress_callback=progress_callback,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("architect: ReAct loop failed")
        return TurnResult(
            status="not_enabled",
            answer=f"Architect agent crashed ({type(exc).__name__}: {exc}).",
        )

    return _smith_agent_result_to_turn_result(result)


def _build_architect_context_block(bp: Blueprint) -> str:
    """Compose the architect-persona + Blueprint-slice context that
    goes at the top of the recall block. Smith reads this and knows
    (a) the domain he built, (b) which entities/pages/workflows he
    authored, (c) that he can and SHOULD use his tools before
    answering — no more 'matches' guesses."""
    parts: list[str] = [
        "## You are the Smith Architect",
        (
            "You authored this application — the entities, the pages, the "
            "workflows. When the user names a screen, USE `list_pages_tool` "
            "to find it and `read_page` to see what's on it BEFORE you "
            "answer. Don't guess. Don't say 'matches' without reading. "
            "When they ask for a new capability, propose the full slice "
            "(entity + page + workflow wiring) and ask ONE approval question."
        ),
    ]
    try:
        from services.smith_blueprint_context import (
            blueprint_to_context, ContextBudget,
        )
        bp_slice = blueprint_to_context(bp, budget=ContextBudget(max_chars=1200))
        if bp_slice.strip():
            parts.extend(["", "## Blueprint (your memory of what you built)", bp_slice])
    except Exception:  # noqa: BLE001
        logger.exception("architect: blueprint_to_context failed")

    try:
        from services.component_catalog import format_component_context
        cat = format_component_context(budget_chars=1200)
        if cat.strip():
            parts.extend(["", cat])
    except Exception:  # noqa: BLE001
        logger.exception("architect: format_component_context failed")

    return "\n".join(parts)


def _smith_agent_result_to_turn_result(result: dict) -> TurnResult:
    """Adapt ``agents.smith_agent.run_smith_agent``'s
    ``{diagnosis, answer, question, handoff, trace, edited_paths}``
    into the ``TurnResult`` shape the caller expects."""
    if not isinstance(result, dict):
        return TurnResult(
            status="not_enabled",
            answer="Architect returned an unrecognized result shape.",
        )
    touched = [str(p) for p in (result.get("edited_paths") or [])]
    trace = list(result.get("trace") or [])
    if result.get("answer"):
        return TurnResult(
            status="resolved",
            answer=str(result["answer"]),
            touched_paths=touched,
            trace=trace,
        )
    if result.get("question"):
        return TurnResult(
            status="asked", answer=str(result["question"]), trace=trace,
        )
    if result.get("handoff"):
        h = result["handoff"] or {}
        return TurnResult(
            status="handoff",
            answer=str(h.get("message") or "Handing off."),
            trace=trace,
        )
    if result.get("diagnosis"):
        return TurnResult(
            status="resolved",
            answer="I have a diagnosis prepared.",
            touched_paths=touched,
            trace=trace,
        )
    return TurnResult(
        status="no_op", answer="No change needed.",
        touched_paths=touched, trace=trace,
    )



# --------------------------------------------------------------------------- #
# Bootstrap wire (Phase C) — Smith owns discovery + planning stages
# for new-app creation. Generation itself stays with the existing
# pipeline (load-bearing, deliberately untouched).
# --------------------------------------------------------------------------- #

# What the caller (chat_with_project) gets back from a bootstrap
# stage run — enough to shape the SSE events already emitted today,
# plus a narrator prose summary Smith authored.
@_dc_dataclass
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


# --------------------------------------------------------------------------- #
# Adapter — TurnResult → the dict shape _handle_smith_turn expects
# --------------------------------------------------------------------------- #

def turn_result_to_legacy_dict(result: TurnResult) -> dict[str, Any]:
    """Convert a SmithSession TurnResult into the shape the existing
    ``_handle_smith_turn`` downstream code reads (answer / question /
    handoff / diagnosis / edited_paths / trace).

    ``needs_user`` becomes a question whose text is the architect's
    prose, with the options[] carried on a side-channel dict the
    caller emits as a `smith_needs_user` SSE event."""
    d: dict[str, Any] = {
        "answer":       None,
        "question":     None,
        "handoff":      None,
        "diagnosis":    None,
        "edited_paths": list(result.touched_paths),
        "trace":        list(result.trace),
        # Not part of the legacy shape — the caller peels these off.
        "_needs_user":  None,
        "_status":      result.status,
        "_diff_summary": result.diff_summary,
    }
    if result.status == "resolved":
        d["answer"] = result.answer
    elif result.status == "asked":
        d["question"] = result.answer
    elif result.status == "needs_user":
        d["question"] = result.answer  # visible message
        d["_needs_user"] = {
            "answer":        result.answer,
            "options":       list(result.options),
            "diff_summary":  result.diff_summary,
            "touched_paths": list(result.touched_paths),
        }
    elif result.status == "handoff":
        d["handoff"] = {"kind": "refine", "message": result.answer}
    elif result.status == "no_op":
        d["answer"] = result.answer
    else:  # not_enabled / rolled_back / other
        d["answer"] = result.answer
    return d
