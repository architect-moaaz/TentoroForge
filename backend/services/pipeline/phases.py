"""Extracted per-phase functions.

Each function is a byte-for-byte lift from the corresponding lines of
:mod:`routers.generate`'s legacy `_run_relay_pipeline` /
`_run_figma_relay_pipeline`, with closure-captured variables promoted
to explicit arguments (usually just ``state: PipelineState``).

Extraction status (Phase 1b of the pipeline cleanup):

Done — clean byte-for-byte lifts, ready for Phase 1e wiring:
- :func:`phase_contract`         text 2029-2078
- :func:`phase_qa`               text 3043-3053 / figma 4855-4867
- :func:`phase_post_generate`    text 3155 / figma 4886  (single call)
- :func:`phase_indexing`         text 3262-3271 / figma 5017-5026
- :func:`phase_journey_gate`     text 3286-3308 / figma 5033-5045 (hints text-only)
- :func:`phase_fidelity_score`   text 3310-3315 / figma 5027-5032
- :func:`phase_app_agent_install` text 3342-3379 / figma 5052-5087
- :func:`phase_seed`             text 2965-2983 / figma 4828-4846
- :func:`phase_parallel_agents`  text 2138-2183 / figma 4402-4441  (Phase 1c)
- :func:`phase_figma_crud_route_fill` figma 4448-4454  (Phase 1c, figma-only)
- :mod:`services.pipeline.binding_gate` — separate module

Not extracted (require registry mutation or entangled closure state;
land as inline blocks in the new spine — Phase 1e):
- ``phase_schema`` — mutates ``registry`` Python var; needs the spine
  to hold the reconciled registry after schema extraction.
- Registry-mutating tail after parallel (`extract_routes` → `merge_section`
  → `validate_registry`) — mutates the spine's ``registry`` var; stays
  inline right after :func:`phase_parallel_agents`.
- ``phase_frontend_text`` / ``phase_frontend_figma`` — Phase 1d.

Every extract:
1. Byte-for-byte lifted from the legacy site (behaviour preservation).
2. Closure references promoted to explicit args.
3. Untested at runtime here — verification comes in Phase 1e when the
   spine calls these and fixtures regen identically. Import-safety is
   verified now.
"""
from __future__ import annotations

import json
import os
from typing import AsyncIterator, Optional

from sse_helpers import sse_event
from services.office_events import (
    agent_start_event,
    agent_complete_event,
    agent_handoff_event,
    parallel_start_event,
    PHASE_TO_AGENTS,
    PHASE_TO_ROOM,
)
from services.pipeline.state import PipelineState


def _deterministic_workflows() -> bool:
    """Deterministic-first workflow generation (default ON).

    Mirrors the top-level helper in :mod:`routers.generate` so this module
    stays self-contained (no back-import to routers). When enabled, the
    BusinessLogic LLM agent is skipped up front — ``generate_workflow_definitions``
    builds executable workflows from the plan + real schema later, and the
    executability guard LLM-repairs only the steps it couldn't infer. Set
    ``FORGE_DETERMINISTIC_WORKFLOWS=off`` to restore LLM-primary generation.
    """
    return os.environ.get("FORGE_DETERMINISTIC_WORKFLOWS", "on").strip().lower() not in (
        "0", "false", "off", "no",
    )


# =============================================================================
# Phase 1 — Contract generation
# =============================================================================


async def phase_contract(
    state: PipelineState,
    plan: dict,
    domain_ctx: Optional[dict] = None,
) -> AsyncIterator[dict]:
    """Phase 1 — deterministic contract builder → LLM fallback → gate → repair.

    Byte-for-byte lift from :mod:`routers.generate` text pipeline lines
    2029-2078. Both pipelines had identical bodies here — the Figma
    version at 4225-4275 is the same code.
    """
    from agents.contract_agent import run_contract_agent
    from services.contract_generator import generate_contracts, ensure_approval_bindings
    from services.phase_gates import check_contract_completeness

    yield sse_event("status", {"message": "Generating contracts..."})
    for aid in PHASE_TO_AGENTS["contract"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["contract"]))

    try:
        _cg = generate_contracts(state.output_dir, plan)
        yield sse_event("log", {"text": f"[Contract] deterministic: {len(_cg.get('generated', []))} file(s), {len(_cg.get('errors', []))} error(s)"})
    except Exception as _cgx:
        yield sse_event("log", {"text": f"[Contract] deterministic generation failed (falling back to LLM): {_cgx}"})

    _contract_precheck = check_contract_completeness(state.output_dir, plan)
    if _contract_precheck["passed"]:
        yield sse_event("log", {"text": "[Contract] deterministic contracts complete — skipping LLM agent"})
    else:
        async for evt in state.stream_phase("Contract", run_contract_agent(state.output_dir, plan, domain_context=domain_ctx)):
            yield evt
    for aid in PHASE_TO_AGENTS["contract"]:
        yield sse_event("office", agent_complete_event(aid))

    # --- CONTRACT GATE: verify contracts cover every entity from plan ---
    contract_gate = check_contract_completeness(state.output_dir, plan)
    if not contract_gate["passed"]:
        gap_count = len(contract_gate["missing"])
        yield sse_event("log", {"text": f"[Contract Gate] {gap_count} gaps found — sending back to contract agent"})
        yield sse_event("status", {"message": f"Completing contracts ({gap_count} gaps)..."})
        try:
            async for evt in state.stream_phase("Contract-Fix", run_contract_agent(state.output_dir, plan, domain_context=domain_ctx)):
                yield evt
        except Exception as e:
            yield sse_event("log", {"text": f"[Contract Gate] Fix attempt failed: {e}"})
    else:
        yield sse_event("log", {"text": "[Contract Gate] ✓ All contracts complete"})

    # Guarantee approval workflows auto-start on entity creation: patch the
    # (LLM-authored) event-bindings.json with any missing <entity>_created →
    # approval-workflow bindings, so a created record starts its review workflow
    # (which pauses + persists a task for Approve/Reject to resolve).
    try:
        _eb = ensure_approval_bindings(state.output_dir, plan)
        if _eb["added"]:
            yield sse_event("log", {"text": f"[Contract] approval start-bindings: added {_eb['added']} <entity>_created binding(s)"})
    except Exception as _ebx:
        yield sse_event("log", {"text": f"[Contract] approval-binding patch skipped: {_ebx}"})

    # Handoff: contract → schema
    yield sse_event("office", agent_handoff_event("contract_writer", "schema_designer", artifact="contracts"))


# =============================================================================
# Phase 6 — Seed data
# =============================================================================


async def phase_seed(
    state: PipelineState,
) -> AsyncIterator[dict]:
    """Phase 6 — seed data generation.

    Byte-for-byte lift from text 2965-2983 / figma 4828-4846 (identical).

    LLM ``run_seed_generator`` produces ``src/db/seed.ts``. Deterministic
    backstop (``ensure_seed_file``) writes a login-able admin user when
    the LLM output is missing/empty.
    """
    from agents.seed_generator import run_seed_generator

    yield sse_event("status", {"message": "Generating seed data..."})
    state.progress.phase_start("seed")
    for pe in state.drain_progress():
        yield pe
    for aid in PHASE_TO_AGENTS["seed"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["seed"]))
    async for evt in state.stream_phase("Seed", run_seed_generator(state.output_dir)):
        yield evt
    # Deterministic backstop: guarantee a login-able admin user if the LLM seed
    # agent didn't produce a usable seed.ts (wedge / timeout / bad output).
    try:
        from services.seed_backstop import ensure_seed_file
        if ensure_seed_file(state.output_dir):
            yield sse_event("log", {"text": "[Seed] LLM seed missing/empty — wrote deterministic admin seed (login: admin / admin123)"})
    except Exception as _seed_ex:  # noqa: BLE001
        yield sse_event("log", {"text": f"[Seed] backstop skipped: {_seed_ex}"})
    for aid in PHASE_TO_AGENTS["seed"]:
        yield sse_event("office", agent_complete_event(aid))


# =============================================================================
# Phase 7 — QA verification
# =============================================================================


async def phase_qa(
    state: PipelineState,
    plan: dict,
    domain_ctx: Optional[dict] = None,
    completeness_report: Optional[dict] = None,
) -> AsyncIterator[dict]:
    """Phase 7 — QA verification.

    Byte-for-byte lift from text 3043-3053 / figma 4855-4867 (identical).

    ``completeness_report`` is the output of the pre-QA completeness pass
    the spine runs immediately before this phase.
    """
    from agents.qa_agent import run_qa_agent

    state.progress.phase_start("qa")
    for pe in state.drain_progress():
        yield pe
    yield sse_event("status", {"message": "Running QA verification..."})
    for aid in PHASE_TO_AGENTS["qa"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["qa"]))
    async for evt in state.stream_phase(
        "QA",
        run_qa_agent(state.output_dir, plan, domain_context=domain_ctx, extra_context=completeness_report),
    ):
        yield evt
    for aid in PHASE_TO_AGENTS["qa"]:
        yield sse_event("office", agent_complete_event(aid))


# =============================================================================
# Post-generate fixes (single-call phase)
# =============================================================================


def phase_post_generate(state: PipelineState, plan: dict) -> None:
    """Apply the post-generate fixes suite.

    Single-call phase — was inline `apply_post_generate_fixes(...)` at
    text 3155 / figma 4886. Not an async generator (no SSE events).
    Both call sites in the legacy pipelines have this same one-liner.
    """
    from services.post_generate_fixes import apply_post_generate_fixes
    apply_post_generate_fixes(state.output_dir, plan)


# =============================================================================
# Phase 9 — Indexing
# =============================================================================


async def phase_indexing(state: PipelineState) -> AsyncIterator[dict]:
    """Phase 9 — indexing.

    Byte-for-byte lift from text 3262-3271 / figma 5017-5026.
    Includes the validator→indexer handoff at the head.
    """
    from agents.indexer import run_indexer

    yield sse_event("office", agent_handoff_event("validator", "indexer", artifact="build_output"))
    yield sse_event("status", {"message": "Indexing application..."})
    for aid in PHASE_TO_AGENTS["indexing"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["indexing"]))
    async for evt in state.stream_phase("Indexer", run_indexer(state.output_dir)):
        yield evt
    for aid in PHASE_TO_AGENTS["indexing"]:
        yield sse_event("office", agent_complete_event(aid))


# =============================================================================
# Journey gate (post-generation E2E verification)
# =============================================================================


async def phase_journey_gate(
    state: PipelineState,
    include_hints: bool = True,
) -> AsyncIterator[dict]:
    """Journey gate — Playwright runs of declared user journeys.

    Text 3286-3308 (includes ``hints`` on failure payload).
    Figma 5033-5045 (omits ``hints``).

    ``include_hints=True`` (default) matches the text-pipeline behaviour;
    pass False for the Figma-parity call site. Strict mode failure
    re-raises after emitting the error event.
    """
    from services.journey_gate import run_journey_gate, JourneyGateFailure

    try:
        _journey_url = os.environ.get("FORGE_JOURNEY_BASE_URL", "http://localhost:3000")
        async for _jevt in run_journey_gate(state.output_dir, base_url=_journey_url):
            yield _jevt
    except JourneyGateFailure as _jgf:
        # Strict mode + failure → surface a loud terminal error that the
        # frontend can distinguish from an infra issue.
        payload: dict = {
            "error": f"journey_gate: {_jgf.summary}",
            "journeys": _jgf.journeys,
        }
        if include_hints:
            payload["hints"] = _jgf.hints
        yield sse_event("error", payload)
        raise
    except Exception as e:
        yield sse_event("log", {"text": f"[Journey] Skipped: {e}"})


# =============================================================================
# Fidelity scoring (advisory, opt-in)
# =============================================================================


async def phase_fidelity_score(
    state: PipelineState,
    plan: dict,
    stream_fidelity_scoring_fn,  # legacy helper still lives in generate.py
) -> AsyncIterator[dict]:
    """Fidelity scoring — advisory output rendered by the frontend.

    Byte-for-byte lift from text 3310-3315 / figma 5027-5032.

    The scoring implementation ``_stream_fidelity_scoring`` still lives
    in :mod:`routers.generate` (has its own set of dependencies that
    haven't been extracted). Callers pass it in explicitly — this phase
    is a wrapper that adds the try/except log-and-skip contract.
    """
    try:
        async for evt in stream_fidelity_scoring_fn(state.output_dir, plan):
            yield evt
    except Exception as e:  # noqa: BLE001
        yield sse_event("log", {"text": f"[Fidelity] Pipeline skipped: {e}"})


# =============================================================================
# App agent auto-install (SP4.5)
# =============================================================================


async def phase_app_agent_install(
    state: PipelineState,
    plan: dict,
    project_id,
) -> AsyncIterator[dict]:
    """Install the app-level agent from ``plan.agent_graph`` when present.

    Byte-for-byte lift from text 3342-3379 / figma 5052-5087 (identical).

    Non-fatal: a failure here (missing MCP server, code_editor timeout,
    etc.) MUST NOT fail the whole app generation — the user can retry
    via the Agent Builder UI. Runs AFTER schema/entities/workflows have
    landed so the code_editor has full app context.

    ``project_id`` may be None (chat pipeline occasionally invokes
    without a project row); in that case the whole block is a no-op.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        if project_id is not None:
            from services.agent_from_plan import install_agent_from_plan
            from database import async_session as _agent_async_session
            from models.project import Project as _Project
            from sqlalchemy import select as _select
            async with _agent_async_session() as _db:
                _proj = (
                    await _db.execute(_select(_Project).where(_Project.id == project_id))
                ).scalar_one_or_none()
                if _proj is not None:
                    yield sse_event("status", {"message": "Installing app agent..."})
                    agent_summary = await install_agent_from_plan(
                        output_dir=state.output_dir,
                        plan=plan,
                        org_id=_proj.org_id,
                        db=_db,
                    )
                    if agent_summary:
                        yield sse_event("status", {
                            "message": f"Agent '{agent_summary['name']}' installed"
                        })
                        yield sse_event("log", {
                            "text": (
                                f"[Agent] installed '{agent_summary['name']}' "
                                f"({agent_summary['node_count']} nodes, "
                                f"{agent_summary['tool_count']} tools)"
                            )
                        })
                        logger.info("[pipeline] agent installed: %s", agent_summary)
    except Exception:  # noqa: BLE001
        logger.exception("[pipeline] agent auto-install failed (non-fatal)")


# =============================================================================
# Phase 3 — Parallel agents (source-conditional; Phase 1c extract)
# =============================================================================


async def phase_parallel_agents(
    state: PipelineState,
    plan: dict,
    domain_ctx: Optional[dict] = None,
) -> AsyncIterator[dict]:
    """Phase 3 — parallel agent execution.

    Byte-for-byte lift with source-conditional inner block:
      * Text pipeline (legacy 2138-2183): BusinessLogic ONLY, gated on
        ``plan.workflows AND not _deterministic_workflows()``.  Per-entity
        API agent + deterministic CRUD fill are DROPPED — the single
        Data Engine catch-all `/api/data/[...path]` serves all CRUD (see
        the `services.api_route_prune` comment at the legacy site).
      * Figma pipeline (legacy 4402-4441): ALWAYS runs ``run_api_agent``,
        conditionally adds BusinessLogic (on ``plan.workflows`` only —
        no deterministic-workflows gate). Then :func:`phase_figma_crud_route_fill`
        runs immediately after to fill any missing CRUD routes.

    Cost/timing accumulators (``state.total_cost`` etc.) are updated
    manually here because ``run_parallel_agents`` bypasses
    ``state.stream_phase`` — it wraps its own idle-timeout inside
    `parallel_runner`, so events flow directly through the pipeline.

    Does NOT do the post-parallel registry reconcile (extract_routes →
    merge_section → validate). That mutates the spine's ``registry``
    Python var and stays inline in the new orchestrator.
    """
    from agents.business_logic_agent import run_business_logic_agent
    from services import chat_flavor
    from services.parallel_runner import run_parallel_agents

    parallel_agents: list = []
    parallel_agent_ids: list[str] = []

    if state.source.is_text:
        # Text: BusinessLogic only, and only when we can't build the
        # workflows deterministically. Skips the ~4-min LLM up front —
        # deterministic emitter runs later in the frontend phase and
        # the executability guard LLM-repairs what it couldn't infer.
        if plan.get("workflows") and not _deterministic_workflows():
            yield sse_event("status", {"message": "Generating business logic (domain workflows + services)..."})
            _cf = chat_flavor.start("workflows")
            if _cf:
                yield sse_event("message", {"text": _cf})
            parallel_agents.append(
                ("BusinessLogic", lambda: run_business_logic_agent(state.output_dir, plan, domain_context=domain_ctx))
            )
            parallel_agent_ids.append("bizlogic_agent")
            yield sse_event("office", agent_handoff_event("schema_designer", "bizlogic_agent", artifact="schema.prisma"))
    else:
        # Figma: always run API agent, add BusinessLogic when workflows exist.
        from agents.api_agent import run_api_agent

        yield sse_event("status", {"message": "Generating auth, API routes, and business logic..."})
        parallel_agents.append(
            ("API", lambda: run_api_agent(state.output_dir, plan, domain_context=domain_ctx))
        )
        parallel_agent_ids.append("api_generator")
        if plan.get("workflows"):
            parallel_agents.append(
                ("BusinessLogic", lambda: run_business_logic_agent(state.output_dir, plan, domain_context=domain_ctx))
            )
            parallel_agent_ids.append("bizlogic_agent")
            yield sse_event("office", agent_handoff_event("schema_designer", "bizlogic_agent", artifact="schema.prisma"))
            _cf = chat_flavor.start("workflows")
            if _cf:
                yield sse_event("message", {"text": _cf})

    if parallel_agents:
        yield sse_event("office", parallel_start_event(parallel_agent_ids))
        for aid in parallel_agent_ids:
            phase_key = {"api_generator": "api", "bizlogic_agent": "business_logic"}.get(
                aid,
                # Text default was "business_logic" (only BusinessLogic
                # runs in that pipeline); Figma default was "api" (falls
                # back to api_generator).
                "business_logic" if state.source.is_text else "api",
            )
            yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM[phase_key]))

        async for evt in run_parallel_agents(state.output_dir, parallel_agents):
            if evt.get("event") == "agent_result":
                data = json.loads(evt["data"])
                state.total_cost += data.get("cost_usd", 0)
                state.total_turns += data.get("num_turns", 0)
                state.total_duration_ms += data.get("duration_ms", 0)
            else:
                yield evt

        for aid in parallel_agent_ids:
            yield sse_event("office", agent_complete_event(aid))

        if plan.get("workflows"):
            _cf = chat_flavor.done("workflows", len(plan.get("workflows") or []))
            if _cf:
                yield sse_event("message", {"text": _cf})


async def phase_figma_crud_route_fill(
    state: PipelineState,
) -> AsyncIterator[dict]:
    """Figma-only — deterministic fill for missing CRUD routes.

    Byte-for-byte lift from figma 4448-4454. Runs immediately after
    :func:`phase_parallel_agents` on the Figma path.

    The api_agent often wedges at the 600s timeout, leaving most
    entities with a DB schema but NO routes — so the app can't
    list/create them. Fill every missing CRUD route set deterministically
    from the schema files. Non-destructive (keeps any LLM-written
    route) and can't time out, so it runs BEFORE the API gate — which
    then passes without an expensive LLM re-run.

    No-op / raises are swallowed; the spine calls this unconditionally
    on the Figma path and the phase decides itself whether it did
    anything meaningful.
    """
    try:
        from services.crud_route_generator import ensure_api_routes
        _filled = ensure_api_routes(state.output_dir)
        if _filled:
            yield sse_event("log", {"text": f"[API] deterministic CRUD fill: wrote {len(_filled)} missing route file(s)"})
    except Exception as _cre:  # noqa: BLE001
        yield sse_event("log", {"text": f"[API] crud route fill skipped: {_cre}"})
