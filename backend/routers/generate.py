"""Generation and chat endpoints — streams SSE events as the agent works."""

import asyncio
import json
import os
import re
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import (
    Project,
    ProjectStatus,
    Conversation,
    AgentJob,
    Version,
    MessageRole,
    MessageType,
    AgentType,
    AgentJobStatus,
)
from schemas.project import GenerateRequest, ChatRequest
from services.project_service import get_project_with_auth
from services.git_service import git_commit, git_revert
from services.post_generate_fixes import apply_post_generate_fixes
from services.office_events import (
    agent_start_event,
    agent_status_event,
    agent_handoff_event,
    agent_complete_event,
    parallel_start_event,
    build_success_event,
    PHASE_TO_AGENTS,
    PHASE_TO_ROOM,
)
from sqlalchemy import select
from sse_helpers import (
    sse_event,
    stream_agent_messages,
    fix_proposal_event,
    fix_applied_event,
    FIX_APPLY_TOKEN,
)
from figma_parser import parse_figma_url
from services.registry import create_registry, save_registry, load_registry, merge_section, reconcile_entities, registry_summary_for_agent
from services import chat_flavor
from services.registry_extractor import extract_entities_from_schema, extract_routes_from_files, extract_components_from_files, extract_pages_from_files
from services.registry_validator import validate_registry, format_validation_report
from services.registry_schema_reconcile import reconcile_registry_to_schema
from config import FIDELITY_MODE_ENABLED, FIDELITY_LOOP_ENABLED
from services.fidelity_loop import FidelityLoopRunner, ProjectContext, PageRef
from services.page_type import infer_page_type
# registry_repair removed — QA agent handles mismatches
from services.generation_buffer import (
    create_session as create_buffer_session,
    get_session as get_buffer_session,
    append_event,
    get_events_since,
    mark_complete,
    wait_for_events,
)

from services.peer_patcher_helpers import (
    load_current_artifacts,
    commit_artifacts,
    registry_snapshot,
    registry_digest,
    token_vocabulary,
)

import logging
import traceback

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generation"])


def _deterministic_workflows() -> bool:
    """Deterministic-first workflow generation (default ON). When enabled, the
    BusinessLogic LLM agent is skipped up front; `generate_workflow_definitions`
    builds executable workflows from the plan + real schema, and the executability
    guard regenerates only the steps it couldn't infer. Set
    FORGE_DETERMINISTIC_WORKFLOWS=off to restore LLM-primary generation."""
    from services.flag_profile import is_on
    return is_on("FORGE_DETERMINISTIC_WORKFLOWS", default=True)

# ---------------------------------------------------------------------------
# Buffered SSE streaming with reconnect support
# ---------------------------------------------------------------------------

def _inject_idx(event: dict, idx: int) -> dict:
    """Inject _idx into the JSON data payload of an SSE event dict."""
    try:
        data = json.loads(event["data"]) if isinstance(event["data"], str) else event["data"]
        data["_idx"] = idx
        return {**event, "data": json.dumps(data)}
    except (json.JSONDecodeError, KeyError, TypeError):
        # Ensure data is always a JSON string, even on error
        if isinstance(event.get("data"), dict):
            return {**event, "data": json.dumps(event["data"])}
        return event


async def buffered_event_stream(
    source: AsyncIterator[dict],
    project_id: str,
) -> AsyncIterator[dict]:
    """Wrap an event_stream() generator with buffering for reconnect support.

    1. Creates a GenerationSession
    2. Starts a background task draining source into the buffer
    3. Yields a 'session' event with the session_id
    4. Tails the buffer, yielding events with heartbeats
    """
    session_id = str(uuid.uuid4())
    buf_session = create_buffer_session(session_id, project_id)

    async def _drain():
        try:
            async for event in source:
                idx = append_event(session_id, event)
                # idx is stored; event is buffered
            mark_complete(session_id, "completed")
        except Exception:
            logger.exception("Generation drain error for session %s", session_id)
            mark_complete(session_id, "failed")

    asyncio.create_task(_drain())

    # First event: tell the client its session_id for reconnect
    yield sse_event("session", {"session_id": session_id})

    # Tail the buffer
    cursor = 0
    while True:
        events = get_events_since(session_id, cursor)
        if events:
            for idx, event in events:
                yield _inject_idx(event, idx)
                cursor = idx + 1
        else:
            # No new events — check if done
            session = get_buffer_session(session_id)
            if session is None or session.status != "running":
                # Drain any last events
                events = get_events_since(session_id, cursor)
                for idx, event in events:
                    yield _inject_idx(event, idx)
                break
            # Wait for new events or send heartbeat
            got_events = await wait_for_events(session_id, timeout=10.0)
            if not got_events:
                yield {"comment": "heartbeat"}


async def reconnect_event_stream(
    session_id: str,
    since: int,
) -> AsyncIterator[dict]:
    """Replay buffered events from `since` and tail if still running."""
    cursor = since

    while True:
        events = get_events_since(session_id, cursor)
        if events:
            for idx, event in events:
                yield _inject_idx(event, idx)
                cursor = idx + 1
        else:
            session = get_buffer_session(session_id)
            if session is None or session.status != "running":
                events = get_events_since(session_id, cursor)
                for idx, event in events:
                    yield _inject_idx(event, idx)
                break
            got_events = await wait_for_events(session_id, timeout=10.0)
            if not got_events:
                yield {"comment": "heartbeat"}


@router.get("/api/projects/{project_id}/generation/active")
async def get_active_generation(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if there's an active generation session for this project.

    Returns the session_id and event count if a generation is still running.
    The frontend calls this after login to auto-reconnect to in-progress generations.
    """
    await get_project_with_auth(project_id, user, db)

    from services.generation_buffer import get_active_session_for_project

    session = get_active_session_for_project(str(project_id))
    if session is None:
        return {"active": False}

    return {
        "active": True,
        "sessionId": session.session_id,
        "eventCount": len(session.events),
        "status": session.status,
    }


@router.get("/api/projects/{project_id}/fix/ab-summary")
async def get_fix_ab_summary(
    project_id: uuid.UUID,
    limit: int = Query(200, ge=1, le=1000),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A/B summary of the Fix-Assistant — compares agent vs single_shot on
    proposals, approval rate, resolve rate, avg iterations + elapsed. Reads
    the ``fix_ab`` metadata dict attached to recent Conversation turns."""
    await get_project_with_auth(project_id, user, db)
    from services.fix_ab_log import summarize
    result = await db.execute(
        select(Conversation)
        .where(Conversation.project_id == project_id,
               Conversation.role == MessageRole.assistant)
        .order_by(Conversation.created_at.desc())
        .limit(limit)
    )
    return summarize(list(result.scalars()))


@router.post("/api/projects/{project_id}/pipeline/resume")
async def resume_pipeline(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """O2 (approval gates): continue a build paused at a FORGE_APPROVAL_GATES
    interrupt. The StateGraph checkpoint for this project's thread holds the
    full pipeline state; re-driving the graph with the same thread_id resumes
    from the gated node (see run_pipeline_graph resume semantics). Streams
    the remainder of the build as the same SSE events /generate emits.

    Also serves as a crash-recovery lever: a build that died mid-phase can
    be resumed here without re-running completed phases."""
    project = await get_project_with_auth(project_id, user, db)
    output_dir = project.output_dir
    if not output_dir or not Path(output_dir).exists():
        raise HTTPException(status_code=404, detail="Project output directory not found")

    plan: dict = {}
    _plan_path = Path(output_dir) / "src" / "contracts" / "plan.json"
    if _plan_path.exists():
        try:
            plan = json.loads(_plan_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            plan = {}

    from services.pipeline_graph import run_pipeline_graph

    async def _stream():
        async for evt in run_pipeline_graph(
                output_dir, plan,
                plan.get("description") or project.description or "",
                project_id=str(project_id)):
            yield evt

    return EventSourceResponse(
        _stream(), ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/projects/{project_id}/generation/{session_id}/events")
async def reconnect_generation(
    project_id: uuid.UUID,
    session_id: str,
    since: int = Query(0, ge=0),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reconnect to a running generation session, replaying events from `since`."""
    await get_project_with_auth(project_id, user, db)

    buf_session = get_buffer_session(session_id)
    if buf_session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if buf_session.project_id != str(project_id):
        raise HTTPException(status_code=403, detail="Session does not belong to this project")

    return EventSourceResponse(
        reconnect_event_stream(session_id, since),
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Map orchestrator intents to agent types for DB records
_INTENT_TO_AGENT_TYPE = {
    "PLAN": AgentType.planner,
    "REFINE": AgentType.refiner,
    "EXPLAIN": AgentType.explainer,
    "SCAFFOLD": AgentType.scaffolder,
    "AGENT": AgentType.scaffolder,  # agents route through scaffolder for now
    "DISCOVER": AgentType.planner,  # discovery routes through planner
}

# Intents that modify code and need validate → index → commit
_CODE_CHANGING_INTENTS = {"REFINE", "SCAFFOLD", "AGENT"}


async def _empty_stream():
    """Empty async iterator — used when no agent needs to run."""
    return
    yield  # type: ignore  # makes this an async generator


async def produce_plan(
    prompt: str,
    output_dir: str,
    domain_context: dict | None = None,
    *,
    emit=None,
    structured_brief=None,
    _should_decompose=None,
    _app_map=None,
    _author_units=None,
    _oneshot=None,
) -> dict:
    """Choose one-shot vs two-stage (skeleton→per-unit) planning.

    One-shot planning is the DEFAULT and stays BYTE-UNCHANGED for small/medium
    apps: when ``should_decompose(prompt)`` is False the one-shot planner is
    called exactly as before and its plan returned.

    Large apps (``should_decompose(prompt)`` True) route through the two-stage
    path: ``run_app_map_planner`` produces a lean skeleton, then
    ``author_all_units`` fills in per-page detail and ASSEMBLES a full plan that
    is shape-identical to a one-shot plan (so every downstream consumer —
    ``_ensure_normalized_plan``, ``build_canonical_registry``, … — is unchanged).
    ``author_all_units`` writes ``<output_dir>/contracts/resource-registry.json``,
    so ``output_dir`` must already exist on disk (the project's output_dir is
    created at project-creation time, well before any planning call).

    Resilience: ANY exception in the two-stage path is logged and falls back to
    the one-shot planner — a broken decomposition must NEVER fail generation.

    The four collaborators are injectable seams (tests pass fakes); each unset
    seam resolves to its real default.
    """
    import inspect

    # ── Resolve seams to their real defaults ──────────────────────────────
    if _should_decompose is None:
        from services.app_decomposition import should_decompose as _should_decompose
    if _app_map is None:
        from agents.app_map_agent import run_app_map_planner as _app_map
    if _author_units is None:
        from services.per_unit_authoring import author_all_units as _author_units
    if _oneshot is None:
        from agents.planner import run_planner_oneshot

        # Fast profile skips the planner's completeness REVISE re-stream (Task 3).
        _profile_here = _gen_profile(output_dir)
        _allow_revise = _profile_here.planner_revise if _profile_here else True

        async def _oneshot(_prompt):
            # No timeout override — inherit run_planner_oneshot's 900s budget.
            # A 300s cap here killed real plans mid-stream: rich domains
            # (e.g. inventory management) stream 5+ minutes of plan JSON.
            return await run_planner_oneshot(
                _prompt, domain_context=domain_context,
                allow_revise=_allow_revise,
            )

    # Slice B+: when a StructuredBrief came from discovery, prepend the
    # AUTHORITATIVE INPUTS block so the planner sees actors + journeys as
    # frozen contracts (see _ONESHOT_SYSTEM_PROMPT's STRUCTURED-INPUT MODE).
    # Rendered ONCE here — every ``_run_oneshot`` call inside this function
    # inherits it. Empty brief renders to '' so legacy paths stay byte-
    # unchanged.
    _auth_block = ""
    if structured_brief is not None:
        try:
            from services.planner_input_render import render_authoritative_block
            _auth_block = render_authoritative_block(structured_brief)
        except Exception:  # noqa: BLE001
            logger.exception("[planner] failed to render authoritative block")
            _auth_block = ""
    if _auth_block:
        prompt = f"{_auth_block}\n\n{prompt}"

    # Discovery narrative expansion (shared with orchestrate_planner via
    # services.plan_wire_pipeline). Env-gated ``FORGE_NARRATIVE_EXPANSION``;
    # falls through unchanged when off or when the LLM errors. Persists to
    # ``<output_dir>/contracts/domain-narrative.md``.
    from services.plan_wire_pipeline import apply_narrative_expansion
    prompt = await apply_narrative_expansion(
        prompt, structured_brief=structured_brief, output_dir=output_dir,
    )

    async def _run_oneshot(prompt_text: str = prompt) -> dict:
        result = _oneshot(prompt_text)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _validated(plan: dict) -> dict:
        """FORGE_PLANNER_V2 gate — deterministic validator + one retry.
        FORGE_PLANNER_CRITIC gate — Actor-Critic loop up to 3 turns.

        Layered:
          Layer A (V2, cheap):  plan_validator.validate_plan + one retry.
                                Catches structural bugs (FK unresolved,
                                dangling workflow targets, unsupported
                                archetypes). ~5ms per validation.
          Layer B (CRITIC):     plan_critic.critique_plan (LLM), up to
                                3 iterations. Catches DOMAIN gaps the
                                validator can't (missing ServiceCatalog,
                                missing management pages, ...).

        Never blocks — on any failure the last-best plan flows through
        so downstream guards + post-generate fixes still run. Flag off
        = no-op returning the plan unchanged.
        """
        def _emit(stage: str, text: str, data: dict | None = None) -> None:
            """Best-effort event push — never lets an emitter error break planning."""
            if emit is None:
                return
            try:
                emit(stage, {"text": text, **(data or {})})
            except Exception:  # noqa: BLE001 — emitter is caller-supplied
                logger.exception("[planner-events] emit(%s) failed", stage)

        # V2 (deterministic validator + one retry) is ON by default now:
        # the workflow-audit slice found every one of these rules — gateway
        # branches, node_missing_next, dangling targets, action_workflow
        # missing, input-coverage — was skipping in a default run, which is
        # what let broken planner output slip through to downstream heuristic
        # repair. Rules are cheap and additive, and the "never blocks" clause
        # means a rule bug can't stall generation. Set FORGE_PLANNER_V2=off
        # explicitly to disable.
        _off = ("0", "false", "no", "off")
        v2_on = os.getenv("FORGE_PLANNER_V2", "on").lower() not in _off
        critic_on = os.getenv("FORGE_PLANNER_CRITIC", "").lower() in ("1", "true", "yes", "on")
        # Fast profile keeps the CHEAP deterministic validation but skips the
        # EXPENSIVE full-plan re-streams (V2 retry + Actor-Critic), each of which
        # adds a 4-8 min planner stream. This is the top fast-vs-deep lever and
        # the top cause of the fast-slower-than-deep inversion (Task 3).
        _pf = _gen_profile(output_dir)
        _allow_v2_retry = _pf.planner_v2_retry if _pf else True
        if _pf and not _pf.planner_critic:
            critic_on = False
        if not v2_on and not critic_on:
            return plan

        try:
            from services.plan_validator import (
                format_violations_for_retry, validate_plan,
                validate_plan_against_brief,
            )
        except Exception:  # noqa: BLE001 — importing the validator must never break generation
            logger.exception("plan_validator import failed; skipping V2 gate")
            return plan

        def _validate(candidate: dict) -> list:
            """One-liner that picks the right validation entry point: with a
            structured brief attached, the authoritative-inputs contract is
            checked ON TOP of the core rules; without one, we fall back to
            core-only (byte-unchanged behaviour). Wrapping this here keeps
            both the initial validation and the retry-validation in sync —
            they'd have drifted if I inlined."""
            if structured_brief is not None:
                v = validate_plan_against_brief(candidate, structured_brief)
            else:
                v = validate_plan(candidate)
            # Executable-plan rules (Slice 1+2). Added to the same flat
            # violation list so the existing retry-hint formatter picks them
            # up automatically — every fired rule flows into the REVISE
            # prompt without a separate pipe. Strict mode (FORGE_STRICT_PLAN)
            # is enforced in `_run_v2_gate` after a retry chance.
            try:
                from services.plan_completeness_validator import (
                    executability_violations,
                )
                for pv in executability_violations(candidate):
                    v.append({
                        "rule": pv.rule,
                        "severity": "error",
                        "message": pv.msg,
                        "location": (
                            f"data_models[{pv.entity}]" if pv.entity else
                            f"workflows[{pv.workflow}]" if pv.workflow else
                            "$"
                        ),
                    })
            except Exception:  # noqa: BLE001 — validator import must never break planning
                logger.exception(
                    "[planner-v2] executability check import failed; skipping"
                )
            return v

        # ── Layer A — deterministic validator + one retry ─────────────────
        async def _run_v2_gate(candidate: dict) -> dict:
            violations = _validate(candidate)
            if not violations:
                logger.info("[planner-v2] plan passed all rules cleanly")
                _emit("v2_clean", "Plan structure passed all checks")
                return candidate
            rules = [v.get("rule") for v in violations][:10]
            logger.warning(
                "[planner-v2] plan has %d violation(s): %s",
                len(violations), rules,
            )
            _emit(
                "v2_violations",
                f"Plan has {len(violations)} structural issue(s) — retrying",
                {"count": len(violations), "rules": rules},
            )
            if not _allow_v2_retry:
                # Fast profile: log the issues (downstream heuristic repair still
                # runs) but don't pay for a full-plan re-stream.
                _emit(
                    "v2_violations_kept",
                    f"Fast build — keeping the first plan ({len(violations)} minor issue(s) logged)",
                    {"count": len(violations)},
                )
                return candidate
            retry_hint = format_violations_for_retry(violations)
            retry_prompt = f"{prompt}\n\n---\n\n{retry_hint}"
            try:
                retried = await _run_oneshot(retry_prompt)
            except Exception:  # noqa: BLE001 — retry crashed; keep candidate
                logger.exception("[planner-v2] retry crashed; keeping plan")
                _emit("v2_retry_error", "Retry crashed — keeping original plan")
                return candidate
            remaining = _validate(retried)
            logger.info(
                "[planner-v2] retry: %d → %d violations",
                len(violations), len(remaining),
            )
            _emit(
                "v2_retry_result",
                f"Retry: {len(violations)} → {len(remaining)} issues",
                {"before": len(violations), "after": len(remaining)},
            )
            return retried if len(remaining) < len(violations) else candidate

        _emit("v2_start", "Reviewing plan structure")
        plan = await _run_v2_gate(plan)

        # ── IRF-M1-T1 REVISE — reprompt planner when 4-axis fields are missing.
        # Detects "LLM_UNAVAILABLE" finding from planner_shape_extension.enrich_plan
        # (fires when app_shape / archetypes / industry / runtime_context / coverage_verdict
        # were all omitted by the LLM and the keyword detector had to fill them). ONE retry
        # only. Off in fast profile (fast profile skips revise re-streams).
        if _allow_revise:
            try:
                from services.planner_shape_extension import enrich_plan as _irf_enrich_peek
                _peek_plan = dict(plan)
                _peek_brief = str(_peek_plan.get("description") or _peek_plan.get("brief") or prompt or "")
                _, _peek_findings = _irf_enrich_peek(_peek_plan, _peek_brief)
                _irf_missing = any(
                    getattr(f, "rule", "") == "LLM_UNAVAILABLE"
                    for f in _peek_findings
                )
            except Exception as _irf_peek_exc:  # noqa: BLE001
                logger.warning("[planner-irf] peek failed; skipping REVISE: %s", _irf_peek_exc)
                _irf_missing = False

            if _irf_missing:
                logger.warning(
                    "[planner-irf] planner emitted no four-axis fields — running ONE IRF REVISE"
                )
                _emit(
                    "irf_revise_start",
                    "Plan missing the four-axis IRF fields — asking planner to add them",
                )
                _irf_retry_hint = (
                    "Your previous plan is missing the REQUIRED four-axis IRF fields: "
                    "app_shape, archetypes, industry, runtime_context, and coverage_verdict. "
                    "These are TOP-LEVEL keys of the plan-json output, alongside "
                    "module_name, data_models, pages, workflows. Emit the FULL revised "
                    "plan with all classic fields preserved verbatim AND the five IRF "
                    "fields added. See the FOUR-AXIS TOPOLOGY section of the system "
                    "prompt for the closed vocabulary."
                )
                _irf_retry_prompt = f"{prompt}\n\n---\n\n{_irf_retry_hint}"
                try:
                    _irf_revised = await _run_oneshot(_irf_retry_prompt)
                    # Only keep the revision if it actually has app_shape now.
                    if isinstance(_irf_revised, dict) and isinstance(_irf_revised.get("app_shape"), dict):
                        logger.info("[planner-irf] REVISE landed the four-axis fields; adopting")
                        _emit("irf_revise_ok", "IRF REVISE succeeded")
                        plan = _irf_revised
                    else:
                        logger.warning("[planner-irf] REVISE did not add app_shape; keeping original")
                        _emit("irf_revise_noop", "IRF REVISE did not add the fields — keeping first plan")
                except Exception:  # noqa: BLE001
                    logger.exception("[planner-irf] REVISE crashed; keeping original plan")
                    _emit("irf_revise_error", "IRF REVISE crashed — keeping first plan")

        # Slice-2 strict-mode gate: if FORGE_STRICT_PLAN is on AND any
        # executability rule still fires after the V2 retry, HALT before
        # emitters see the plan. Strict is opt-in per environment — off by
        # default, so this is telemetry-only until you flip it. When it
        # fires, the error carries the violation list so the caller can
        # surface actionable feedback to the user.
        try:
            from services.plan_completeness_validator import (
                enforce_plan_executability,
                is_strict_plan_enabled,
            )
            if is_strict_plan_enabled():
                enforce_plan_executability(plan)
        except Exception as _strict_err:
            # PlanNotExecutableError bubbles up to the router; anything else
            # is a bug in the validator itself and shouldn't block generation.
            from services.plan_completeness_validator import PlanNotExecutableError
            if isinstance(_strict_err, PlanNotExecutableError):
                _emit(
                    "v2_strict_halt",
                    f"Plan is not executable ({len(_strict_err.violations)} rule(s)) — "
                    "halting per FORGE_STRICT_PLAN.",
                    {"violations": [v.rule for v in _strict_err.violations]},
                )
                raise
            logger.exception("[planner-v2] strict-mode check failed; continuing")

        if not critic_on:
            return plan

        # ── Layer B — Actor-Critic loop (max 3 turns) ─────────────────────
        try:
            from agents.plan_critic import critique_plan
            from services.plan_critic_prompt import build_actor_retry_prompt
        except Exception:  # noqa: BLE001 — critic import failed; ship V2 plan
            logger.exception("plan_critic import failed; skipping CRITIC gate")
            return plan

        history: list[dict] = []  # [{plan, verdict, gaps, n_blockers}]
        prior_gaps: list[dict] = []
        current_plan = plan

        _emit("critic_start", "Reviewing plan quality with the critic")
        for turn in range(1, 4):  # 3 turns max
            _emit(
                "critic_turn_start",
                f"Critic turn {turn} — reviewing plan",
                {"turn": turn},
            )
            det_violations_now = _validate(current_plan)
            critique = await critique_plan(
                plan=current_plan,
                user_brief=prompt,
                deterministic_violations=det_violations_now,
                prior_critic_gaps=prior_gaps,
            )
            n_blockers = sum(1 for g in critique["gaps"] if g["severity"] == "blocker")
            n_important = sum(1 for g in critique["gaps"] if g["severity"] == "important")
            domain = critique["inferred_domain"][:60]
            logger.info(
                "[planner-critic] turn %d verdict=%s blockers=%d important=%d "
                "domain=%s",
                turn, critique["verdict"], n_blockers, n_important, domain,
            )
            _emit(
                "critic_verdict",
                (
                    f"Turn {turn} ({domain}): {critique['verdict']} — "
                    f"{n_blockers} blocker(s), {n_important} important"
                ),
                {
                    "turn": turn,
                    "verdict": critique["verdict"],
                    "blockers": n_blockers,
                    "important": n_important,
                    "domain": domain,
                },
            )
            history.append({
                "plan": current_plan,
                "verdict": critique["verdict"],
                "gaps": critique["gaps"],
                "n_blockers": n_blockers,
                "n_important": n_important,
            })

            # Decision 3: reject short-circuits — don't burn more turns
            # on a plan the critic thinks is unsalvageable. The
            # gaps + questions ride out on `history` so the caller
            # (future button + user chat) can pick them up.
            if critique["verdict"] == "reject":
                logger.warning(
                    "[planner-critic] verdict=reject on turn %d; short-circuiting",
                    turn,
                )
                _emit(
                    "critic_rejected",
                    f"Critic rejected the plan on turn {turn}",
                    {"turn": turn},
                )
                break

            # approve → done, use this plan
            if critique["verdict"] == "approve":
                logger.info(
                    "[planner-critic] approved on turn %d after %d iteration(s)",
                    turn, turn,
                )
                _emit(
                    "critic_approved",
                    f"Plan approved on turn {turn}",
                    {"turn": turn},
                )
                return current_plan

            # revise → invoke actor with the corrective prompt
            if turn == 3:  # hit the cap — no more revisions
                logger.warning(
                    "[planner-critic] hit 3-turn cap without approval; "
                    "shipping best-so-far"
                )
                _emit(
                    "critic_capped",
                    "Hit 3-turn cap — shipping best plan so far",
                )
                break

            _emit(
                "critic_revising",
                f"Revising plan based on {n_blockers + n_important} gap(s)",
                {"turn": turn, "blockers": n_blockers, "important": n_important},
            )
            retry_prompt = build_actor_retry_prompt(
                original_brief=prompt,
                prior_plan=current_plan,
                critic_gaps=critique["gaps"],
            )
            try:
                revised = await _run_oneshot(retry_prompt)
            except Exception:  # noqa: BLE001 — actor crashed; keep the plan we had
                logger.exception(
                    "[planner-critic] actor retry crashed on turn %d; "
                    "shipping best-so-far", turn,
                )
                _emit(
                    "critic_retry_error",
                    "Revision crashed — shipping best plan so far",
                )
                break
            # Re-run V2 on the revision so a structural regression in the
            # LLM's edit gets a chance to be corrected before the next
            # critic pass.
            current_plan = await _run_v2_gate(revised)
            prior_gaps = critique["gaps"]

        # Decision 1 + 2: ship best-so-far by fewest blockers,
        # tiebreak by fewest important gaps.
        best = min(
            history,
            key=lambda h: (h["n_blockers"], h["n_important"]),
        )
        logger.info(
            "[planner-critic] shipping best-so-far: blockers=%d important=%d",
            best["n_blockers"], best["n_important"],
        )
        _emit(
            "critic_best_so_far",
            (
                f"Shipping best-so-far — {best['n_blockers']} blocker(s), "
                f"{best['n_important']} important"
            ),
            {"blockers": best["n_blockers"], "important": best["n_important"]},
        )
        return best["plan"]

    from services.plan_wire_pipeline import apply_plan_wires as _apply_audit_wire  # noqa: E501

    # ── Branch: one-shot (default) vs two-stage decomposition ─────────────
    try:
        decompose = bool(_should_decompose(prompt))
    except Exception:  # noqa: BLE001 — never let the gate itself fail generation
        logger.warning(
            "produce_plan: should_decompose failed; using one-shot", exc_info=True
        )
        return _apply_audit_wire(await _validated(await _run_oneshot()))

    if not decompose:
        return _apply_audit_wire(await _validated(await _run_oneshot()))

    # Two-stage: skeleton → per-unit authoring. Fall back on ANY failure.
    try:
        # ``_app_map`` (run_app_map_planner) is sync but its default LLM
        # boundary is async and it uses ``asyncio.run`` internally. When
        # called from this async context that explodes with "cannot be
        # called from a running event loop." Run it in a worker thread
        # so its internal loop has no parent — the fix documented in
        # tests/test_orchestrate_planner_decomposition.py::test_decomposition_survives_nested_event_loop.
        skeleton = await asyncio.to_thread(_app_map, prompt, domain_context)
        # Same nested-loop trap as _app_map: sync author_all_units calls
        # sync author_page_detail which does asyncio.run() on an async
        # LLM query — run in a worker thread so its internal loop has
        # no parent. Without this every page-detail authoring throws
        # and the whole two-stage attempt returns skeleton pages.
        plan = await asyncio.to_thread(_author_units, skeleton, output_dir)
        return _apply_audit_wire(await _validated(plan))
    except Exception:  # noqa: BLE001 — decomposition broke; degrade to one-shot
        logger.warning(
            "produce_plan: two-stage decomposition failed; falling back to one-shot",
            exc_info=True,
        )
        return _apply_audit_wire(await _validated(await _run_oneshot()))


async def _stream_produce_plan(
    prompt: str,
    output_dir: str,
    domain_context: dict | None = None,
    structured_brief=None,
):
    """Async generator that runs `produce_plan` and streams its
    planner-v2 / planner-critic events live as SSE events.

    Yields ``(kind, payload)`` tuples where ``kind`` is either:
      * ``"event"``  — payload is already a formatted SSE line
                       (from :func:`sse_event`) ready to yield upstream.
      * ``"plan"``   — payload is the finished plan dict; emitted
                       exactly once as the final tuple. If planning
                       raised, the exception propagates from here
                       instead.

    Usage::

        plan = None
        async for kind, payload in _stream_produce_plan(...):
            if kind == "event":
                yield payload
            else:  # "plan"
                plan = payload

    Bridge implementation uses ``asyncio.Queue`` so events surface in the
    stream as they happen, not batched at the end.
    """
    import asyncio

    # Capability gate — decide up-front whether this prompt fits what the
    # pipeline can build (CRUD-over-database) or centers on client-side
    # interactivity (calculator/game/timer) that would produce a coherent
    # but empty shell. Observe-mode by default; hard-enforces only when
    # FORGE_CAPABILITY_GATE is on. Never blocks planning on gate errors.
    try:
        from services.capability_gate import (
            enforce_capability_gate,
            InteractiveAppRefused,
        )
        classification = enforce_capability_gate(prompt or "")
        if classification.get("shape") == "interactive":
            # Observe-only: gate is off, but classifier fired — surface it
            # as a warning so telemetry and the UI can see the miss.
            yield "event", sse_event("capability_warning", {
                "message": (
                    "This prompt looks interactive-app-shaped "
                    f"({classification.get('reason', '')}). "
                    "Generation will proceed but likely produce a CRUD shell "
                    "around the concept — the interactive core (state, "
                    "arithmetic, animation) is outside the DSL."
                ),
                "classification": classification,
            })
        elif classification.get("shape") == "computational":
            # `needs_workflow` — when the ask includes "email/notify/save/…"
            # alongside the computational token, the tool needs a workflow
            # to hand its result off to (send email, notify webhook, …).
            # The deterministic short-circuit can't author that; fall
            # through to the LLM planner which the HARD-STOP block guides
            # to emit a computational archetype WITH workflows[] populated.
            if classification.get("needs_workflow"):
                yield "event", sse_event("capability_shortcircuit_deferred", {
                    "message": (
                        "Detected computational tool with workflow intent "
                        f"({', '.join(classification.get('workflow_intent_matched') or [])}) — "
                        "routing through LLM planner so it can author the workflow "
                        "handoff (keeps entities=[] but populates workflows[])."
                    ),
                    "classification": classification,
                })
                # fall through to normal produce_plan below
            else:
                # BYPASS the LLM planner — the general PLANNER_SYSTEM_PROMPT
                # has MANDATORY sections (persist actors as User entity,
                # generate workflow_tasks, emit auth pages) that were
                # designed for CRUD apps. Even with the appended
                # COMPUTATIONAL guidance the LLM falls back to CRUD-shaped
                # output for calculator/converter/quiz asks (inventing
                # CalculationSession entity, /login, /visitors). Emit a
                # canonical single-page plan deterministically so downstream
                # stages see the intent verbatim.
                from services.computational_plan import build_computational_plan
                plan = build_computational_plan(prompt or "", classification)
                yield "event", sse_event("capability_shortcircuit", {
                    "message": (
                        f"Detected {', '.join(classification.get('matched') or ['tool'])} — "
                        "routing to computational archetype (deterministic plan; "
                        "bypasses LLM planner)."
                    ),
                    "classification": classification,
                })
                yield "plan", plan
                return
    except InteractiveAppRefused as refused:
        # Gate is ON and prompt is interactive — emit refusal and stop
        # before spending any planner turns.
        yield "event", sse_event("capability_refusal", {
            "message": str(refused),
            "classification": refused.classification,
        })
        return
    except Exception:
        # Fail open: never let a gate bug block real generation.
        pass

    queue: asyncio.Queue = asyncio.Queue()

    def _emit(stage: str, payload: dict) -> None:
        # Called from produce_plan._validated on the same event loop.
        queue.put_nowait({"stage": stage, **payload})

    task = asyncio.create_task(
        produce_plan(
            prompt, output_dir,
            domain_context=domain_context,
            emit=_emit,
            structured_brief=structured_brief,
        )
    )

    while True:
        # Race the task's completion against the next queued event so
        # events surface promptly AND we unblock the moment planning
        # returns (even if the queue is empty).
        get_task = asyncio.create_task(queue.get())
        done, _ = await asyncio.wait(
            {task, get_task}, return_when=asyncio.FIRST_COMPLETED
        )

        if get_task in done:
            payload = get_task.result()
            yield "event", sse_event("planner_thought", payload)
        else:
            get_task.cancel()

        if task in done:
            # Drain any remaining queued events before yielding the plan.
            while not queue.empty():
                payload = queue.get_nowait()
                yield "event", sse_event("planner_thought", payload)
            plan = task.result()  # re-raises on planning failure
            yield "plan", plan
            return


def _ensure_normalized_plan(plan: dict) -> dict:
    """Guarantee a plan is in the canonical pipeline shape, whatever path it
    arrived by (one-shot, interactive SDK planner, figma, or re-extracted JSON).

    `_normalize_oneshot_plan` (entities-DICT → `data_models` LIST) and
    `_annotate_page_types` (page types, entity inference, auth-gating, route +
    action hygiene) are wired ONLY into `run_planner_oneshot`. Plans entering
    via the interactive planner / figma analysis / `_extract_plan_json` are used
    RAW — a raw plan expressing entities as the `entities` DICT makes
    `create_registry` / `build_schema_files` iterate `data_models` → 0 entities
    → broken app (Pipeline Reliability Atlas L1).

    Applying it here at the pipeline entry closes that gap. Both helpers are
    idempotent: `_normalize_oneshot_plan` only converts when an `entities` dict
    is present AND `data_models` is absent (a no-op on an already-normalized
    plan), and `_annotate_page_types` is documented as deterministic/idempotent,
    so re-running on a one-shot plan that was already normalized is safe.
    Best-effort — never blocks generation; returns the input plan on any error.
    """
    if not isinstance(plan, dict):
        return plan
    try:
        from agents.planner import _annotate_page_types, _normalize_oneshot_plan
        plan = _annotate_page_types(_normalize_oneshot_plan(plan))
    except Exception as _norm_exc:  # noqa: BLE001 — never block generation
        logger.warning("_ensure_normalized_plan skipped: %s", _norm_exc)
        return plan
    # IRF-M1-T1 + M1-T10 + M0-T1: four-axis enrichment + industry/domain
    # compat bridge. Fills any missing/invalid axis field from keyword
    # detectors (M1-T6/T7) and shadow-copies industry↔domain so legacy
    # readers keep working. Findings are collected for the REVISE loop
    # but not enforced here (planner-side REVISE is separate).
    try:
        from services.planner_shape_extension import enrich_plan
        brief = str(plan.get("description") or plan.get("brief") or plan.get("prompt") or "")
        plan, findings = enrich_plan(plan, brief)
        error_findings = [f for f in findings if f.severity == "error"]
        if error_findings:
            logger.info(
                "[shape_extension] %d error finding(s) on plan enrichment; sample=%r",
                len(error_findings), error_findings[0].rule,
            )
    except Exception as _shape_exc:  # noqa: BLE001
        logger.warning("shape enrichment skipped: %s", _shape_exc)
    return plan


def _schema_files_complete(output_dir: str, plan: dict) -> bool:
    """True iff every entity in plan.data_models produced BOTH
    src/db/schema/<slug>.ts AND src/types/<slug>.ts on disk.

    Used to decide whether the deterministic schema builder covered every
    entity (skip the LLM schema agent) or left gaps (run it as fallback).
    """
    try:
        from services.schema_builder import (
            _normalize_models,
            _reg_slug,
            _reg_table,
            RESERVED_TABLES,
        )
        from services.resource_registry import build_canonical_registry
    except Exception:
        return False
    root = Path(output_dir)
    models = _normalize_models(plan.get("data_models"))
    if not models:
        return False
    # Consult the SAME naming authority `build_schema_files` writes with — the
    # Canonical Resource Registry, which owns each entity's hint-aware slug/table
    # (e.g. a plan `table:"equipment"` hint stays `equipment`, not re-pluralized
    # to `equipments`). Using the hint-blind `to_slug` here made the gate look for
    # a file the writer never wrote → it reported "incomplete" → the LLM schema
    # agent ran over a complete deterministic build and emitted the OTHER plural
    # → duplicate schema files → `unknown table` + build break.
    reg_entities = build_canonical_registry(plan).get("entities", {})
    for m in models:
        name = m["name"]
        # Reserved auth tables (e.g. users) are owned by the template, not the
        # builder — don't require builder-emitted files for them. Match the
        # writer's reserved check, which reads the registry table (not to_table).
        if _reg_table(reg_entities, name) in RESERVED_TABLES:
            continue
        slug = _reg_slug(reg_entities, name)
        if not (root / "src" / "db" / "schema" / f"{slug}.ts").exists():
            return False
        if not (root / "src" / "types" / f"{slug}.ts").exists():
            return False
    return True


async def _run_npm_install(output_dir: str) -> AsyncIterator[dict]:
    """Install npm deps as a plain subprocess.

    The deterministic schema path skips the LLM schema agent, which used to be
    the thing that ran `npm install`. This runs it off the LLM. Idempotent —
    skips when node_modules already exists (e.g. the LLM fallback path already
    installed). Best-effort: logs loudly on failure but never raises."""
    try:
        root = Path(output_dir)
        if (root / "node_modules").exists():
            yield sse_event("log", {"text": "[npm] node_modules present — skipping install"})
            return
        if not (root / "package.json").exists():
            yield sse_event("log", {"text": "[npm] no package.json — skipping install"})
            return
        yield sse_event("log", {"text": "[npm] Installing dependencies (npm install)..."})

        async def _install(extra_args: list[str]) -> tuple[int | None, bytes]:
            proc = await asyncio.create_subprocess_exec(
                "npm", "install", *extra_args,
                cwd=output_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _out, _err = await asyncio.wait_for(proc.communicate(), timeout=300)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                return None, b""
            return proc.returncode, _err or b""

        rc, err = await _install([])
        if rc is None:
            yield sse_event("log", {"text": "[npm] ⚠ install timed out after 300s (non-fatal)"})
            return
        if rc != 0 and b"ERESOLVE" in err:
            # Upstream peer-dep drift (e.g. next-auth 4.24.15 bumping its
            # nodemailer peer past the template pin) shouldn't strand the app
            # without node_modules — retry accepting the legacy resolution.
            yield sse_event("log", {"text": "[npm] peer-dep conflict — retrying with --legacy-peer-deps"})
            rc, err = await _install(["--legacy-peer-deps"])
            if rc is None:
                yield sse_event("log", {"text": "[npm] ⚠ retry timed out after 300s (non-fatal)"})
                return
        if rc == 0:
            yield sse_event("log", {"text": "[npm] ✓ dependencies installed"})
        else:
            _tail = err.decode("utf-8", "replace")[-500:]
            yield sse_event("log", {"text": f"[npm] ⚠ install failed (exit {rc}, non-fatal): {_tail}"})
    except Exception as _npm_exc:
        yield sse_event("log", {"text": f"[npm] ⚠ install error (non-fatal): {_npm_exc}"})


async def _offer_design_templates(plan: dict, output_dir: str):
    """After a plan is ready, research + offer design templates (renderable looks).
    Yields SSE events. Shared by every plan_ready path. Best-effort — never raises."""
    try:
        from agents.design_researcher import research_design_templates
        from services.design_template_store import save_offered
        domain = (plan.get("domain") or plan.get("industry")
                  or (plan.get("app") or {}).get("domain") or "")
        requirement = str(plan.get("description") or plan.get("summary") or "")
        yield sse_event("status", {"message": "Researching design aesthetics…"})
        tpls = await research_design_templates(str(domain), requirement, n=3)
        if output_dir:
            save_offered(output_dir, tpls)
        yield sse_event("log", {"text": f"[Design] Suggested {len(tpls)} design templates: "
                                        f"{', '.join(t.get('name', '') for t in tpls)}"})
        yield sse_event("design_templates_ready", {"templates": tpls})
    except Exception as exc:  # noqa: BLE001
        yield sse_event("log", {"text": f"[Design] Template research skipped: {exc}"})


def _clean_schemas_dir(output_dir: str) -> int:
    """Remove output_dir/src/schemas/ so stale schemas from a previous
    generation don't bleed into a fresh run. Returns count of files removed.
    Safe to call on first-time runs (no-op when directory absent)."""
    schemas_dir = Path(output_dir) / "src" / "schemas"
    if not schemas_dir.exists():
        return 0
    removed = 0
    for p in sorted(schemas_dir.rglob("*"), reverse=True):
        if p.is_file():
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        elif p.is_dir() and p != schemas_dir:
            try:
                p.rmdir()
            except OSError:
                pass
    return removed


async def _stream_fidelity_scoring(output_dir: str, plan: dict) -> AsyncIterator[dict]:
    """Run fidelity scoring against the rendered scaffold and yield SSE events.

    Gated by FIDELITY_SCORING_ENABLED. Wrapped in try/except by callers — this
    helper itself surfaces individual page errors as 'fidelity' events but does
    not catch the outer setup. Default base URL is 6503 (the render-scaffold);
    6501 is the editor frontend and will silently 404."""
    import os
    if os.environ.get("FIDELITY_SCORING_ENABLED", "").lower() not in ("1", "true", "yes"):
        return
    from services.fidelity_runner import run_fidelity_scoring
    scaffold_base = os.environ.get("SCAFFOLD_BASE_URL", "http://localhost:6503")
    project_id = Path(output_dir).name
    score_count = 0
    score_total = 0.0
    findings: list[dict] = []
    async for evt in run_fidelity_scoring(
        output_dir=output_dir, project_id=project_id,
        plan=plan, scaffold_base_url=scaffold_base,
    ):
        if evt["type"] == "score":
            score_count += 1
            score_total += evt["score_0_to_10"]
            findings.extend(evt.get("findings") or [])
            yield sse_event("log", {
                "text": f"[Fidelity] {evt['page']} ({evt['page_type']}): "
                        f"{evt['score_0_to_10']:.1f}/10 — {evt['qualitative_notes'][:120]}"
            })
        elif evt["type"] == "skip":
            yield sse_event("log", {
                "text": f"[Fidelity] Skipped {evt.get('page','-')}: {evt['reason']}"
            })
        elif evt["type"] == "error":
            yield sse_event("log", {
                "text": f"[Fidelity] Error on {evt.get('page','-')}: {evt['error']}"
            })
        yield sse_event("fidelity", evt)
    if score_count > 0:
        avg = score_total / score_count
        yield sse_event("log", {"text": f"[Fidelity] Mean score: {avg:.2f}/10 across {score_count} pages"})

    # Turn the critique into repairs. Collected across every page and routed
    # ONCE — the visual passes are app-wide and idempotent, so running them
    # per page would be pure churn. Global findings (palette, type scale) are
    # reported, never auto-applied: one authority owns them for the whole app.
    if findings:
        from services.visual_findings import route_visual_findings
        by_type: dict[str, int] = {}
        for f in findings:
            by_type[f["type"]] = by_type.get(f["type"], 0) + 1
        yield sse_event("log", {
            "text": "[Fidelity] " + str(len(findings)) + " finding(s): "
                    + ", ".join(f"{t}×{n}" for t, n in sorted(by_type.items()))
        })
        # Hand it the WHOLE list: route_visual_findings partitions internally
        # and returns the global ones as unhandled, so refusing to repair them
        # is visible in the disposition instead of silently dropped here.
        disp = await asyncio.to_thread(route_visual_findings, output_dir, findings)
        if disp["ran"]:
            yield sse_event("log", {
                "text": f"[Fidelity] Repaired {disp['fixed']} item(s) via "
                        + ", ".join(disp["ran"])
            })
        for f in disp["unhandled"]:
            scope = "global — needs a design change" if f["type"] in {
                "palette_mismatch", "type_scale_off"} else "no repair seam"
            yield sse_event("log", {
                "text": f"[Fidelity] Unrepaired {f['type']} on {f['route']} ({scope})"
            })
        yield sse_event("fidelity_repair", {
            "findings": findings, "fixed": disp["fixed"],
            "ran": disp["ran"], "unhandled": disp["unhandled"],
        })


# Binding + registry validation gate — extracted to services/pipeline/binding_gate.py
# (Phase 1b of the pipeline cleanup). Re-exported here so any external
# caller that imports from routers.generate keeps working; new code should
# import from services.pipeline.binding_gate directly.
from services.pipeline.binding_gate import (
    binding_gate_is_strict as _binding_gate_is_strict,
    stream_binding_gate as _stream_binding_gate,
)
# Phase 1e wrapper — one entry point for the generation pipeline.
# Legacy _run_relay_pipeline / _run_figma_relay_pipeline stay as internal
# implementations that run_pipeline dispatches into based on PlanSource.
from services.pipeline import PlanSource, run_pipeline


def _gen_profile(output_dir: str):
    """The user's Fast/Complete profile for this run (or None). The profile is
    the single source of truth for the speed levers — review cycles + planner
    retry gates — so Fast is actually fast and Complete is the thorough one."""
    try:
        from services.generation_profile import load_profile
        return load_profile(output_dir)
    except Exception:  # noqa: BLE001
        return None


async def _real_build_ok(output_dir: str) -> tuple[bool, str]:
    """Authoritative build check for the review gate — runs the REAL
    `npm run build` and returns (passed, joined_error_text) from its exit code.
    Replaces the fragile keyword-matching of the validator's prose, which could
    report "build passed" on a broken app (or waste cycles on a clean one).
    Never raises."""
    try:
        from services.verify_pipeline import _run_build
        res = await _run_build(output_dir)
        return bool(res.get("passed")), "\n".join(res.get("errors", []) or [])
    except Exception as e:  # noqa: BLE001
        return False, f"real build check errored: {e}"


def _plan_summary(plan: dict | None) -> str:
    """Short prose grounding for the brief author: entity names + page mix.

    Mirrors the shape ``services.register_selector._build_register_prompt``
    already uses, so the two LLM calls describe the same app the same way.
    Returns "" when the plan is missing or unrecognisable — ``author()``
    tolerates an empty summary and reasons from the domain alone.
    """
    if not isinstance(plan, dict):
        return ""
    entities = plan.get("entities") or {}
    if isinstance(entities, dict):
        names = list(entities.keys())[:8]
    elif isinstance(entities, list):
        names = [
            e.get("name", "?") if isinstance(e, dict) else str(e)
            for e in entities[:8]
        ]
    else:
        names = []

    parts: list[str] = []
    if names:
        parts.append(f"Entities: {', '.join(names)}")
    pages = plan.get("pages") or []
    if isinstance(pages, list) and pages:
        kinds: dict[str, int] = {}
        for pg in pages:
            if isinstance(pg, dict):
                k = str(pg.get("type") or pg.get("archetype") or "page")
                kinds[k] = kinds.get(k, 0) + 1
        if kinds:
            shape = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
            parts.append(f"Pages: {len(pages)} ({shape})")
    return ". ".join(parts)


async def _author_and_persist_brief(
    output_dir: str,
    domain_ctx: dict,
    plan: dict,
    figma_context: dict | None = None,
    project_id: str | None = None,
) -> None:
    """Author a design brief for the discovered domain and drop it at
    ``contracts/brief.json``. No-op unless the ``FORGE_BRIEF_AUTHOR``
    flag is set.

    Spec A Slice 6d — when ``figma_context`` is present (a
    Figma-sourced project), route to ``brief_from_figma`` (pure
    deterministic aggregator; no LLM) so palette/typography/radius
    survive byte-exact from the Figma source with per-field locks.
    Otherwise fall through to the LLM authoring path.

    Errors are logged and swallowed — brief authoring must never block
    generation.
    """
    if os.getenv("FORGE_BRIEF_AUTHOR", "0") != "1":
        return
    try:
        from pathlib import Path as _Path

        domain = (domain_ctx or {}).get("domain") or "General"

        # Figma path — deterministic aggregator, no LLM.
        if figma_context and (figma_context.get("design_tokens") or {}):
            from services.brief_from_figma import brief_from_figma, BriefFromFigmaError
            try:
                brief = brief_from_figma(figma_context, domain=domain)
                logger.info(
                    "[brief] extracted from Figma for domain=%s (source=figma, "
                    "brand=%s, %d locked palette fields)",
                    domain, brief.palette.brand, len(brief.palette.locked_fields),
                )
            except BriefFromFigmaError as _fex:
                # Figma context was too sparse — fall through to LLM author.
                logger.info("[brief] figma extraction sparse (%s); falling back to LLM author", _fex)
                brief = None
        else:
            brief = None

        # LLM authoring path. The docstring above has always promised this
        # ("Otherwise fall through to the LLM authoring path") but the call
        # was missing: every non-Figma build assigned ``brief = None`` and
        # then hit ``brief.model_dump_json()`` below, so brief authoring
        # raised AttributeError on 100% of prompt-based generations. The
        # except-block logged it "non-fatal" and the run continued with no
        # contracts/brief.json — which is why ``brief_consume`` had nothing
        # to read. ``design_brief_author.author`` existed the whole time
        # with zero non-test callers.
        if brief is None:
            from services.design_brief_author import author as _author_brief, BriefAuthorError
            try:
                brief = await _author_brief(domain, plan_summary=_plan_summary(plan))
                logger.info(
                    "[brief] authored via LLM for domain=%s (source=llm)", domain,
                )
            except BriefAuthorError as _bex:
                logger.warning("[brief] LLM author failed (non-fatal): %s", _bex)
                brief = None

        # Slice A (2026-08-13) — populate visual_lock from a domain preset
        # BEFORE persisting so downstream (brief_to_design_spec, design_dna,
        # design_compiler) reads the locked values instead of re-deriving.
        # The preset is a FALLBACK, not a correction: it must not overwrite a
        # palette measured from a Figma file or a design-reference screenshot.
        # `visual_lock.is_active()` alone answered the wrong question — see
        # services/design_brief_preset_policy.py for the bug it let through.
        try:
            from services.design_brief_preset_policy import should_apply_preset
            if should_apply_preset(brief):
                from services.visual_lock_presets import pick_preset_from_plan
                _lock = pick_preset_from_plan(plan)
                brief.visual_lock = _lock
                logger.info(
                    "[visual-lock] applied preset=%s for domain=%s",
                    _lock.preset_name, domain,
                )
        except Exception as _vl_exc:  # noqa: BLE001 — never fail brief authoring
            logger.warning("[visual-lock] preset apply failed (non-fatal): %s", _vl_exc)

        if brief is None:
            # Nothing to persist. Downstream (brief_to_design_spec,
            # design_dna, the design agent's brief_consume path) all treat a
            # missing brief.json as "no brief" and fall back — so returning
            # here degrades cleanly instead of raising.
            logger.warning(
                "[brief] no brief produced for domain=%s — skipping persist", domain,
            )
            return

        target = _Path(output_dir) / "contracts" / "brief.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(brief.model_dump_json(indent=2))
        logger.info("[brief] persisted → %s", target)

        # Composition Recipe Library (behind FORGE_COMPOSITION_RECIPES).
        # Derive page_recipes from the plan and merge into the just-written
        # brief. Deterministic word-overlap picker per plan page → recipe key;
        # existing recipes on the brief win. Silent no-op when the flag is off.
        # Wrapped in its own try/except so a recipe derivation failure never
        # taints brief authoring.
        try:
            from services.composition.pipeline_hook import is_flag_on as _crl_on
            if _crl_on():
                from services.composition.apply_recipes import derive_persist_apply
                _recipes = derive_persist_apply(output_dir, plan)
                if _recipes:
                    logger.info(
                        "[composition] wrote %d page recipes into brief.json", len(_recipes),
                    )
        except Exception as _crl_exc:  # noqa: BLE001
            logger.warning("[composition] derive/apply failed (non-fatal): %s", _crl_exc)
    except Exception as _brief_exc:  # noqa: BLE001
        logger.exception("[brief] author failed (non-fatal): %s", _brief_exc)


async def _run_relay_pipeline(
    output_dir: str,
    plan: dict,
    description: str,
    figma_context: dict | None = None,
    project_id: uuid.UUID | None = None,
    domain_context: dict | None = None,
) -> AsyncIterator[dict]:
    """Run the unified relay team pipeline for code generation.

    Handles BOTH text-based and Figma-based generation. The only difference:
    - Figma context is passed to the Design Agent (which extracts colors from screenshots)
    - Figma context is passed to the IR pipeline (which may inject Figma page IR)

    `domain_context`: when supplied (typically by /chat after the user approves
    the discovery dossier), skip the inline `run_domain_discovery` call in
    Layer 1 and use the provided dict directly. Caller is responsible for
    user-edits being applied to that dict before passing it in. When None,
    Layer 1 runs discovery itself (legacy path / direct /generate endpoint).

    Pipeline:
      design → contracts → schema → parallel(auth, api, biz) → IR frontend → seed → qa → validate → index
    """
    # LG-2 + O1 (LangGraph migration): the checkpointed StateGraph spine is
    # now the DEFAULT for prompt builds in schema mode — same SSE-event
    # generator contract, plus crash-resume from the last completed phase.
    # FORGE_LANGGRAPH_PIPELINE=0 opts back into this hand-rolled relay.
    # Figma builds (figma_context set) and non-schema frontend paths
    # (SCHEMA_MODE off / IR path) always use the relay — the spine ports
    # only the default schema path (see services/pipeline_graph.py).
    if os.environ.get("FORGE_LANGGRAPH_PIPELINE", "1") != "0" and figma_context is None:
        from services.schema_pipeline import SCHEMA_MODE_ENABLED as _SCHEMA_MODE
        if _SCHEMA_MODE:
            from services.pipeline_graph import run_pipeline_graph
            logger.info("[pipeline] StateGraph spine selected (FORGE_LANGGRAPH_PIPELINE default-on)")
            async for evt in run_pipeline_graph(
                    output_dir, plan, description,
                    domain_context=domain_context,
                    project_id=str(project_id) if project_id else None):
                yield evt
            return
        logger.info("[pipeline] SCHEMA_MODE off — StateGraph spine unsupported, using relay")

    from agents.contract_agent import run_contract_agent
    from agents.schema_agent import run_schema_agent
    from agents.auth_agent import run_auth_agent
    from agents.api_agent import run_api_agent
    from agents.design_agent import run_design_agent, extract_design_spec, save_design_spec
    from agents.domain_agent import run_domain_discovery, persist_discovery
    import shutil
    from pathlib import Path

    # Pipeline-trace instrumentation. Catches silent drops (SSE client
    # disconnect → coroutine cancelled, or unhandled exception in a
    # deep helper) that would otherwise leave the log dead-quiet with
    # no verdict. Every entry gets a logger.info; every exit — success,
    # exception, OR cancellation — is logged with elapsed time and the
    # reason. Uses BaseException so asyncio.CancelledError is captured.
    _pipeline_t0 = time.perf_counter()
    _pipeline_last_phase: dict[str, str] = {"name": "(none)"}
    logger.info(
        "[pipeline] ENTER relay pipeline output_dir=%s project_id=%s",
        output_dir, project_id,
    )

    # Single normalization choke point: guarantee the plan is in canonical shape
    # (entities-DICT → data_models LIST, page-type/auth/route hygiene) regardless
    # of the ingestion path (one-shot already normalizes; interactive / figma /
    # re-extracted plans arrive raw). Idempotent — a no-op on already-normalized
    # plans (Pipeline Reliability Atlas L1).
    plan = _ensure_normalized_plan(plan)

    # IRF-M5-T2 (lite): stamp the ambient SessionContext for this run so
    # every stage / guard / Smith tool that opts in (via
    # ``session_context.current()``) sees the same substrate. Silent
    # no-op guard — a plumbing failure here MUST NOT abort generation;
    # historic behavior is preserved for callers that don't read the
    # context. Persisted to disk at pipeline end so Smith can consume
    # verify_history across turns (M5-T9).
    try:
        from services.session_context import from_plan as _sc_from_plan
        from services.session_context import set_current as _sc_set_current
        _session_ctx = _sc_from_plan(plan)
        _sc_set_current(_session_ctx)
    except Exception:  # noqa: BLE001 — telemetry infra, not a hard dep
        _session_ctx = None

    # IRF-M2-T7: coverage-verdict gate. Runs first — before any generation
    # stage — so an out-of-scope brief spends zero tokens on downstream
    # authoring. Tolerant of missing plan.coverage_verdict (M1-T1 planner
    # emission lands separately) — a missing verdict is treated as
    # in_scope. extension_needed verdicts log to substrate_gap_log.jsonl
    # and proceed. out_of_scope verdicts halt with a structured payload
    # the SSE surface (M2-T3, future) will render as OutOfScopeCard.
    try:
        from services.coverage_verdict_gate import evaluate as _gate_evaluate
        from services.substrate_gap_log import append as _gap_log_append
        _brief_summary = (
            plan.get("description") or plan.get("brief") or plan.get("prompt") or description or ""
        )[:500]
        _gen_slug = str(Path(output_dir).name) if output_dir else ""
        _gate = _gate_evaluate(plan, brief_summary=_brief_summary, gen_slug=_gen_slug)
        if _gate.action == "proceed_and_log_gap":
            if _gate.gap_log_entry is not None:
                _gap_log_append(_gate.gap_log_entry)
            logger.info(
                "[coverage_verdict] extension_needed logged: missing=%s",
                _gate.missing_dimensions,
            )
        elif _gate.action == "halt":
            logger.info(
                "[coverage_verdict] halting pipeline — status=%s nearest=%r",
                _gate.verdict_status, _gate.nearest_supported,
            )
            # Emit a structured SSE event so the frontend can render
            # the refusal card. Uses the existing sse_event helper —
            # M2-T3 will formalize the message_type name in the client
            # renderer; today it flows as a JSON payload the chat pane
            # can display as a message.
            yield sse_event("coverage_verdict", _gate.refusal_payload or {})
            return
    except Exception as _cvg_exc:  # noqa: BLE001 — never block gen on gate crash
        logger.warning("[coverage_verdict] gate crashed, proceeding: %s", _cvg_exc)

    # Progress tracker — MUST be initialised before any code path can call
    # `_progress.phase_start(...)`. The discovery `else` branch below reads
    # `_progress`; without this early init, Python's local-scope rule turns
    # that read into UnboundLocalError ("cannot access local variable
    # '_progress' where it is not associated with a value") on every recreate-
    # plan / direct-generate path where `domain_context` is None. Root-cause
    # fix for B-022.2 — deterministic + covers every code path in the
    # pipeline that will ever emit progress.
    from services.progress import ProgressTracker as _ProgressTracker
    _pending_progress: list[dict] = []
    _progress = _ProgressTracker(
        emit_fn=lambda k, d: _pending_progress.append(sse_event(k, d)),
    )
    def _drain_progress():
        while _pending_progress:
            yield _pending_progress.pop(0)

    # Stamp the app-level archetype onto the plan when a keyword classifier
    # matches the description. Downstream generators (workflow_generator,
    # runtime_injector, archetype-owned emitters) all key off plan["archetype"];
    # without this stamp they silently fall through to generic CRUD paths and
    # domain workflows like ScanProductWorkflow are never authored. Classifier
    # is cheap keyword matching (no LLM) and idempotent — if the plan already
    # carries an archetype it wins.
    try:
        if isinstance(plan, dict) and not (plan.get("archetype") or plan.get("app_archetype")):
            from services.app_design_catalog import classify_app_archetype as _classify_arche
            _brief_text = (
                plan.get("description") or plan.get("brief") or plan.get("prompt") or ""
            )
            _matched_archetype = _classify_arche(_brief_text)
            if _matched_archetype:
                plan["archetype"] = _matched_archetype
                logger.info("[plan] stamped archetype=%s from classifier", _matched_archetype)
    except Exception as _arche_exc:  # noqa: BLE001 — never block generation
        logger.warning("[plan] archetype stamp skipped: %s", _arche_exc)

    # Guarantee the archetype's entry-point pages exist on the plan. The
    # planner sometimes emits list/detail/history but forgets the primary
    # ingress (e.g. /scan for visual-product-search). This runs BEFORE
    # schema generation so the injected pages get authored like any
    # planner-declared page.
    try:
        from services.archetypes import (
            ensure_required_pages as _ensure_pages,
            ensure_required_workflows as _ensure_wfs,
            ensure_required_columns as _ensure_cols,
        )
        _n = _ensure_pages(plan)
        if _n:
            logger.info("[plan] injected %d required page(s) for archetype=%s",
                        _n, plan.get("archetype"))
        _nw = _ensure_wfs(plan)
        _nc = _ensure_cols(plan)
        if _nw or _nc:
            logger.info("[plan] injected %d required workflow(s), %d column(s) "
                        "for archetype=%s", _nw, _nc, plan.get("archetype"))
    except Exception as _req_exc:  # noqa: BLE001
        logger.warning("[plan] required-pages injection skipped: %s", _req_exc)

    # ── Domain re-classification (planner enum → 17-bucket keyword) ─────
    # The planner LLM is constrained to a 5-value ``domain`` enum
    # (``general | hr | fintech | healthcare | saas``); real briefs like
    # "yoga studio" or "recruitment platform" always collapse to
    # ``general`` and every downstream domain-aware seam (photo picker,
    # palette bias, industry_design register) then falls back to generic
    # behaviour. Re-run ``_classify_domain`` and overwrite ``plan.domain``
    # when the planner returned generic. Fail-closed — leaves plan intact
    # on any error. Shared with the Figma pipeline via plan_finalize.
    try:
        from services.plan_finalize import reclassify_plan_domain as _reclass_domain
        _before, _after, _changed = _reclass_domain(plan)
        if _changed:
            yield sse_event("log", {"text": (
                f"[domain] reclassified {_before!r} → {_after!r}"
            )})
    except Exception as _dom_exc:  # noqa: BLE001
        logger.warning("[domain] reclassify skipped: %s", _dom_exc)

    # ── Prompt-directive parser ─────────────────────────────────────────
    # Extract STRUCTURED directives the user embedded in prose ("Preset =
    # trust-navy", "Row-click → /x/[id]", "Gauge 0-150 target 110"),
    # write them to ``plan.hints``, stamp ``plan.archetype`` from the
    # vocab keyword table when the primary classifier missed, and lift
    # any preset into ``plan.brief_hints`` for the brief author.
    try:
        from services.plan_directive_parser import enrich_plan_with_directives
        _added = enrich_plan_with_directives(plan)
        if _added:
            logger.info("[plan] directive-parser found: %s", ", ".join(_added))
    except Exception as _dir_exc:  # noqa: BLE001 — never block generation
        logger.warning("[plan] directive parser skipped: %s", _dir_exc)

    # ── Persist requirement.json ─────────────────────────────────────────
    # First-class user-requirement artifact (Slice 2 of requirement-as-
    # central-piece). Preserves the original prompt + parsed directives
    # + amendments across regens and Smith edits. Every downstream
    # generator and Smith turn reads it as authority — the plan and
    # schemas are derivations of THIS.
    try:
        from services.requirement import ensure_requirement
        _prompt_txt = plan.get("description") or plan.get("brief") or plan.get("prompt") or ""
        ensure_requirement(output_dir, _prompt_txt)
    except Exception as _req_exc:  # noqa: BLE001
        logger.warning("[requirement] persist skipped: %s", _req_exc)

    # Persist the canonical plan so any downstream service can read it as
    # authority. `plan_field_lookup` reads this to answer questions like
    # "what enum_values did the plan declare for Application.status?" —
    # avoiding the enum-harvester's polluted merge. Any post-generate
    # pass that wants plan-declared field metadata reads from here.
    try:
        from services.plan_canonicalizer import canonicalize_plan
        plan, _canon_report = canonicalize_plan(plan)
        _canon_changes = {k: v for k, v in _canon_report["summary"].items() if v}
        if _canon_changes:
            logger.info("[plan-canonicalize] normalized: %s", _canon_changes)
        _contracts_dir = Path(output_dir) / "src" / "contracts"
        _contracts_dir.mkdir(parents=True, exist_ok=True)
        (_contracts_dir / "plan.json").write_text(
            json.dumps(plan, indent=2, default=str), encoding="utf-8"
        )
    except Exception as _plan_persist_exc:  # noqa: BLE001
        logger.warning("[plan-persist] skipped: %s", _plan_persist_exc)

    # ── Plan workflows → workflows/*.json (domain business logic) ──────
    # The pipeline must be self-sufficient: the router also calls this
    # before invoking us, but headless callers (fleet, metrics scripts,
    # CI) drive run_pipeline directly — without this, every plan-declared
    # domain workflow (BookClass, ApproveLeave, BatchIngest…) silently
    # never reaches disk and the delivery gate reports launcher_missing
    # on all of them (fleet Phase-0 finding: 14 errors across 5 apps).
    # Idempotent — per-workflow skip inside.
    try:
        _sync_workflows_from_plan(output_dir, plan)
    except Exception as _wf_sync_exc:  # noqa: BLE001
        logger.warning("[workflow-sync] skipped: %s", _wf_sync_exc)

    # ── Dashboard maquette (content decision before page authoring) ─────
    # One focused LLM turn: pick 3-4 KPIs, the primary chart, the activity
    # feed, and the hero framing. Writes contracts/dashboard-maquette.json
    # so the downstream deterministic dashboard-composer can rebuild the
    # dashboard schema with real bindings + rich content. Gate: profile's
    # richness contract (KPI row + chart) — shared with the Figma pipeline
    # via plan_finalize.author_dashboard_maquette_if_enabled.
    try:
        from services.plan_finalize import (
            author_dashboard_maquette_if_enabled as _author_maq_if_enabled,
            author_collection_maquettes_if_enabled as _author_col_maq_if_enabled,
            author_record_maquettes_if_enabled as _author_rec_maq_if_enabled,
            ensure_composition_reference as _ensure_comp_ref,
        )
        # Montage first — the three authors below read what it writes.
        _comp_ref = await _ensure_comp_ref(
            plan, output_dir, str(project_id) if project_id else None)
        if _comp_ref is not None:
            yield sse_event("log", {"text": (
                "[montage] composition reference: "
                + (", ".join(sorted(_comp_ref.get("screens") or {}))
                   or "layout only"))})
        _maq = await _author_maq_if_enabled(plan, output_dir)
        if _maq is not None:
            yield sse_event("log", {"text": (
                f"[maquette] wrote {len(_maq.get('kpis') or [])} KPIs, "
                f"chart={'y' if _maq.get('primary_chart') else 'n'}, "
                f"activity={'y' if _maq.get('activity') else 'n'}, "
                f"hero={'y' if _maq.get('hero') else 'n'}"
            )})
        # Phase 2 fanout — collection + record maquettes (per-page LLM
        # authoring, capped in plan_finalize). Same profile gate as
        # dashboard so all three run together or none does.
        _col_maq = await _author_col_maq_if_enabled(plan, output_dir)
        if _col_maq is not None:
            yield sse_event("log", {"text": (
                f"[maquette/collection] wrote {len(_col_maq)} collection maquette(s)"
            )})
        _rec_maq = await _author_rec_maq_if_enabled(plan, output_dir)
        if _rec_maq is not None:
            yield sse_event("log", {"text": (
                f"[maquette/record] wrote {len(_rec_maq)} record maquette(s)"
            )})
    except Exception as _maq_exc:  # noqa: BLE001
        logger.warning("[maquette] pass failed: %s", _maq_exc)

    # ── Layer 1 — Foundation: domain discovery ────────────────────────────
    # Replaces the previous detect_domain + copy_knowledge_files combo. The
    # discovery agent (web-search enabled) produces a structured dossier
    # covering persona blocks per agent role, design patterns with citations,
    # visual language tendencies, compliance notes, and common pitfalls.
    # Written to src/contracts/discovery.json so it's inspectable post-hoc
    # and re-usable on regen. No fallback to a curated KB by design — if
    # discovery fails after one retry, the generation aborts with a clear
    # error rather than continuing on a degenerate domain context.
    #
    # When `domain_context` is supplied as a kwarg (the /chat user-approval
    # path), skip the inline discovery call and use the provided dict.
    # This is what enables the chat-approval pause-and-resume pattern.
    if domain_context is not None:
        domain_ctx = domain_context
        persist_discovery(output_dir, domain_ctx)
        await _author_and_persist_brief(output_dir, domain_ctx, plan,
                                        figma_context=figma_context,
                                        project_id=str(project_id) if project_id else None)
        domain_label = domain_ctx.get("domain", "Generic")
        yield sse_event("log", {
            "text": (
                f"[Discovery] ✓ Using user-approved domain context: "
                f"{domain_label} "
                f"({len(domain_ctx.get('designPatterns', []))} pattern(s), "
                f"{len(domain_ctx.get('commonPitfalls', []))} pitfall(s))"
            )
        })
    else:
        yield sse_event("status", {"message": "Researching domain context..."})
        _progress.phase_start("discovery")
        for _pe in _drain_progress():
            yield _pe
        yield sse_event("log", {"text": "[Discovery] Researching domain (web search enabled)..."})
        try:
            domain_ctx = await run_domain_discovery(description, plan, enable_web_search=True)
        except Exception as _disc_exc:
            yield sse_event("log", {
                "text": f"[Discovery] ⚠ FAILED: {_disc_exc} — aborting generation"
            })
            raise
        persist_discovery(output_dir, domain_ctx)
        await _author_and_persist_brief(output_dir, domain_ctx, plan,
                                        figma_context=figma_context,
                                        project_id=str(project_id) if project_id else None)
        domain_label = domain_ctx.get("domain", "Generic")
        n_patterns = len(domain_ctx.get("designPatterns", []))
        n_pitfalls = len(domain_ctx.get("commonPitfalls", []))
        elapsed = domain_ctx.get("elapsedSeconds", 0)
        yield sse_event("log", {
            "text": (
                f"[Discovery] ✓ Domain: {domain_label} | "
                f"{n_patterns} design pattern(s), {n_pitfalls} pitfall(s) | "
                f"{elapsed}s | persisted to src/contracts/discovery.json"
            )
        })

    # ── TEMPLATE FLOOR: Copy pre-tested infrastructure files ──
    # These provide a guaranteed-working foundation. Agents customize ON TOP of these.
    # Auth, config, hooks, providers, shared components — never LLM-generated.
    template_dir = Path(__file__).parent.parent / "templates" / "app-foundation"
    # FIGMA-FLOOR: unconditional copy — the `not target.exists()` guard below
    # protects every Figma-authored page from being overwritten, so it's safe
    # to run this for Figma projects too. Skipping the whole floor (the old
    # `and not figma_context` gate) also skipped src/db/index.ts,
    # src/lib/schema-page.tsx, and the entire runtime — leaving Figma apps
    # with dead imports (@/lib/schema-page not found, seed.ts requires ./index).
    if template_dir.exists():
        dst = Path(output_dir)
        copied = 0
        for src_file in template_dir.rglob("*"):
            if src_file.is_file():
                rel = src_file.relative_to(template_dir)
                target = dst / rel
                # Don't overwrite files that already exist (Figma-authored
                # pages, or files from a previous generation, always win).
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, target)
                    copied += 1
        yield sse_event("log", {"text": f"[Templates] Copied {copied} foundation files (auth, hooks, UI components)"})

    # Reachability guard (SP3.2): the planner is free to skip full CRUD pages for
    # supporting entities — make sure none ends up orphaned (no page AND no relation).
    # Runs BEFORE create_registry so any promoted page flows into the registry + page gen.
    try:
        from services.app_design_guardrail import ensure_entity_reachability
        plan, _reach = ensure_entity_reachability(plan)
        if _reach["promoted"]:
            yield sse_event("log", {"text": f"[Design] promoted orphaned entities to pages: {_reach['promoted']}"})
        yield sse_event("log", {"text": f"[Design] entities — primary: {len(_reach['primary'])}, inline: {len(_reach['supporting_inline'])}, promoted: {len(_reach['promoted'])}"})
    except Exception as _r_ex:
        yield sse_event("log", {"text": f"[Design] reachability guard skipped: {_r_ex}"})

    # Canonical Resource Registry — the single naming authority, built once from the
    # finalized plan. ADDITIVE for now (persisted, not yet consumed); later phases flip
    # each generator to read it instead of re-deriving names.
    try:
        from services.resource_registry import build_canonical_registry, write_registry
        _canon_reg = build_canonical_registry(plan)
        write_registry(_canon_reg, output_dir)
        logger.info("resource-registry.json written: %d entities", len(_canon_reg.get("entities", {})))
    except Exception as e:  # noqa: BLE001 — never block generation
        logger.warning("build_canonical_registry skipped: %s", e)

    # FK-semantics authority — classify every FK column's role (actor/domain/
    # tenancy/plain) from the registry's real FK targets. Emitted right after the
    # canonical registry so backend consumers read roles, never guess by name.
    try:
        from services.fk_semantics import emit_fk_semantics
        emit_fk_semantics(output_dir)
    except Exception as e:  # noqa: BLE001 — never block generation
        logger.warning("emit_fk_semantics skipped: %s", e)

    # Initialize contract registry from plan
    registry = create_registry(plan)
    save_registry(output_dir, registry)
    _removed = _clean_schemas_dir(output_dir)
    if _removed > 0:
        yield sse_event("log", {"text": f"[Cleanup] Removed {_removed} stale schema file(s) from src/schemas/"})
    yield sse_event("log", {"text": f"[Registry] Initialized: {len(registry['entities'])} entities, {len(registry['api_routes'])} routes"})

    # Emit the app-design report (archetypes + features chosen, after guardrail).
    try:
        from services.app_design_guardrail import normalize_app_design
        import json as _json
        _, _design_report = normalize_app_design(plan)
        (Path(output_dir) / "app-design-report.json").write_text(_json.dumps(_design_report, indent=2))
        _archs = {p.get("archetype") for p in _design_report["pages"]}
        yield sse_event("log", {"text": f"[Design] archetypes: {sorted(a for a in _archs if a)}"})
    except Exception as _d_ex:
        yield sse_event("log", {"text": f"[Design] report skipped: {_d_ex}"})

    from agents.business_logic_agent import run_business_logic_agent
    from agents.component_agent import run_component_agent
    from agents.page_agent import run_page_agent
    from agents.qa_agent import run_qa_agent
    from agents.validator import run_validator
    from agents.indexer import run_indexer
    from services.parallel_runner import run_parallel_agents, stream_with_idle_timeout

    total_cost = 0.0
    total_turns = 0
    total_duration = 0

    # Per-phase wall-clock timing (seconds). Written to generation-timing.json
    # at the end of the pipeline. Bookkeeping is best-effort — never fatal.
    _phase_timings: dict[str, float] = {}

    # Progress tracker was hoisted to the top of this pipeline so the
    # discovery-else branch above couldn't crash with UnboundLocalError
    # (B-022.2). Init here is intentionally removed — the earlier one is
    # authoritative. The phase→key map still lives here so it stays adjacent
    # to the phase-emitting call sites below.
    _STREAM_PHASE_TO_KEY = {
        "Design":        "design",
        "Contract":      "contract",
        "Contract-Fix":  "contract",
        "Schema":        "schema",
        "BusinessLogic": "bizlogic_api",
        "API":           "bizlogic_api",
        "Component":     "components",
        "Component-Fix": "components",
        "Page":          "pages",
        "Page-Fix":      "pages",
        "UX-Fix":        "pages",
        "Workflow":      "workflows",
        "Workflow-Fix":  "workflows",
        "Auth-Fix":      "auth",
    }

    def _write_timing():
        try:
            total = sum(_phase_timings.values())
            (Path(output_dir) / "generation-timing.json").write_text(
                json.dumps({"phases": _phase_timings, "total_seconds": round(total, 2)}, indent=2)
            )
        except Exception:
            pass

    async def _stream_phase(name: str, messages):
        """Stream a single agent phase, accumulating costs.

        Wraps the agent iterator with an idle timeout so a wedged
        claude_agent_sdk subprocess (no events for AGENT_TIMEOUT_SECONDS)
        fails fast with AgentTimeoutError instead of hanging the pipeline.
        """
        nonlocal total_cost, total_turns, total_duration
        _t0 = time.perf_counter()
        _pipeline_last_phase["name"] = name
        logger.info("[phase-trace] START %s", name)
        # Fix #3/#4/#7 — emit authoritative progress at phase entry.
        _phase_key = _STREAM_PHASE_TO_KEY.get(name)
        if _phase_key:
            _progress.phase_start(_phase_key)
            for _pe in _drain_progress():
                yield _pe
        _phase_ok = False
        try:
            async for evt in stream_with_idle_timeout(name, output_dir, messages):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt
            _phase_ok = True
        finally:
            _elapsed = time.perf_counter() - _t0
            _phase_timings[name] = _phase_timings.get(name, 0.0) + _elapsed
            if _phase_ok:
                logger.info("[phase-trace] END %s ok elapsed=%.1fs", name, _elapsed)
            else:
                logger.warning(
                    "[phase-trace] EXIT %s early (cancel/error) elapsed=%.1fs",
                    name, _elapsed,
                )
            try:
                yield sse_event("log", {"text": f"[Timing] {name}: {_elapsed:.1f}s"})
            except Exception:
                pass

    # Phase 0: Design Agent — LLM researches UI/UX design for this app
    yield sse_event("status", {"message": "Researching UI/UX design..."})
    yield sse_event("log", {"text": f"[Design] Researching design for {domain_label} app..."})

    # Find Figma screenshots if available
    from pathlib import Path as _Path
    figma_screenshots = sorted(str(p) for p in _Path(output_dir).glob("reference*.png"))

    collected_design_text: list[str] = []
    # ── DESIGN DNA ──
    # Derive a distinct, domain-appropriate design identity for THIS project
    # (deterministic: seeded by project id + domain). It (a) briefs the design
    # agent so the LLM refines a committed identity instead of reverting to the
    # statistical-average look, (b) is the merge-base under the agent's spec so
    # prose-degraded values never silently revert to defaults, and (c) is the
    # complete fallback when the agent's fence fails to parse.
    design_dna: dict | None = None
    dna_brief: str | None = None
    try:
        from services.design_dna import derive_design_dna, prompt_brief
        # The planner's `domain` is a 5-value enum ("general|hr|fintech|
        # healthcare|saas") that cannot express real products — 'general' used
        # to SHADOW the rich discovery label ("Pet Social & Matchmaking").
        # Feed the archetype matcher everything: both domain strings plus the
        # discovery description, app/module name, entity names and page names.
        # match_archetype is additive bag-of-words scoring — more signal only
        # ever helps.
        _plan_domain = str((plan or {}).get("domain") or "").strip()
        if _plan_domain.lower() in ("general", "generic", ""):
            _plan_domain = ""
        _dna_domain = " ".join(x for x in (_plan_domain, str(domain_label or "")) if x).strip() or "general"
        _ctx_parts: list[str] = [str(description or (plan or {}).get("description") or "")]
        if isinstance(domain_ctx, dict):
            _ctx_parts.append(str(domain_ctx.get("description") or ""))
            _ctx_parts.extend(str(a) for a in (domain_ctx.get("domainAliases") or [])[:6])
        _ctx_parts.append(str((plan or {}).get("app_name") or ""))
        _ctx_parts.append(str((plan or {}).get("module_name") or ""))
        _ents = (plan or {}).get("entities")
        if isinstance(_ents, dict):
            _ctx_parts.extend(list(_ents.keys())[:20])
        for _p in ((plan or {}).get("pages") or [])[:26]:
            if isinstance(_p, dict):
                _ctx_parts.append(str(_p.get("name") or _p.get("title") or ""))
        _dna_context = " ".join(x for x in _ctx_parts if x)[:2000]
        # Load the design brief (if authored) so the design_language
        # composer can veto brutalist picks (hard-offset shadows, grid
        # backgrounds, JetBrains-Mono headings) on warm/calm briefs.
        # Best-effort — no brief = no veto = same behaviour as before.
        _brief_for_dna = None
        try:
            from services.design_brief_to_prompt import load_brief_from_disk
            _brief_for_dna = load_brief_from_disk(output_dir)
        except Exception:  # noqa: BLE001
            _brief_for_dna = None
        design_dna = derive_design_dna(
            project_id=Path(output_dir).name,
            domain=_dna_domain,
            context=_dna_context,
            # The discovery dossier already researched this product's REAL
            # visual language (palette character, typography tone, density).
            # It is the strongest signal available — honour it over defaults.
            dossier=domain_ctx if isinstance(domain_ctx, dict) else None,
            brief=_brief_for_dna,
        )
        dna_brief = prompt_brief(design_dna)
        _dna_path = Path(output_dir) / "src" / "contracts" / "design-dna.json"
        _dna_path.parent.mkdir(parents=True, exist_ok=True)
        _dna_path.write_text(json.dumps(design_dna, indent=2))
        _L = design_dna.get("layout", {})
        yield sse_event("log", {"text": (
            f"[Design DNA] {design_dna['archetype']} · {design_dna.get('mode','light')} mode · "
            f"{design_dna['typography']['pairing']} · primary "
            f"{design_dna['color']['primary']} · {design_dna['shape']['radiusScale']} radii · "
            f"{design_dna['rhythm']['density']} density")})
        yield sse_event("log", {"text": (
            f"[Design DNA] composition — auth:{_L.get('auth')} · "
            f"dashboard:{_L.get('dashboard')} · list:{_L.get('list')} · "
            f"detail:{_L.get('detail')} · chrome:{_L.get('chrome')}")})
    except Exception as _dna_exc:
        logger.exception("[Design DNA] derivation failed")
        yield sse_event("log", {"text": f"[Design DNA] skipped: {_dna_exc}"})

    # ─── 21st.dev PRE-FETCH ───────────────────────────────────────────────────
    # Fetch 2–3 domain-shaped component references from 21st.dev BEFORE the
    # design branch decision, so both the canonical (brief→spec) and legacy
    # (LLM) paths have references on disk for downstream page-schema authoring.
    # Behind FORGE_21ST_MCP + FORGE_21ST_API_KEY; no-op when disabled or on
    # network failure.
    try:
        from services import magic_mcp as _magic
        if _magic.is_enabled():
            from services import magic_prefetch as _prefetch
            from services.design_brief_to_prompt import load_brief_from_disk as _load_brief_early
            _early_brief = _load_brief_early(output_dir)
            _prefetch_domain = None
            _prefetch_brief_dict = None
            if _early_brief is not None:
                _prefetch_domain = getattr(_early_brief.identity, "domain", None)
                try:
                    _prefetch_brief_dict = json.loads(_early_brief.model_dump_json())
                except Exception:
                    _prefetch_brief_dict = None
            if not _prefetch_domain:
                _prefetch_domain = (plan or {}).get("domain")
            yield sse_event("log", {"text": f"[21st] Pre-fetching references for domain={_prefetch_domain!r}"})
            _ref_paths = await _prefetch.prefetch_references(
                output_dir, domain=_prefetch_domain, brief=_prefetch_brief_dict,
            )
            yield sse_event("log", {"text": f"[21st] Pre-fetch wrote {len(_ref_paths)} references"})
    except Exception as _pref_exc:
        yield sse_event("log", {"text": f"[21st] Pre-fetch skipped: {_pref_exc}"})

    # ─── BRIEF-CANONICAL BRANCH (Spec A Slice 3) ─────────────────────────────
    # When FORGE_BRIEF_CANONICAL=1 and a brief.json exists on disk, skip the
    # design LLM entirely — the brief is the sole design authority and maps
    # deterministically to a design-spec via brief_to_design_spec. Legacy path
    # runs when the flag is off or when no brief exists. FORGE_LEGACY_DESIGN_AGENT=1
    # forces legacy even with a brief present (emergency escape hatch).
    from services.brief_to_design_spec import brief_to_design_spec
    from services.design_brief_to_prompt import load_brief_from_disk

    _canonical = (
        os.getenv("FORGE_BRIEF_CANONICAL", "0") == "1"
        and os.getenv("FORGE_LEGACY_DESIGN_AGENT", "0") != "1"
    )
    canonical_brief = load_brief_from_disk(output_dir) if _canonical else None

    if canonical_brief is not None:
        # Sole visual authority — no LLM in the design decision chain.
        yield sse_event("log", {"text": (
            f"[Design] Brief-canonical path — no LLM (domain={canonical_brief.identity.domain}, "
            f"brand={canonical_brief.palette.brand}, source={canonical_brief.identity.domain})")})
    else:
        # Legacy path — run the design agent LLM.
        async for evt in _stream_phase("Design", run_design_agent(
            output_dir, plan, domain_context=domain_ctx,
            figma_screenshots=figma_screenshots if figma_screenshots else None,
            dna_brief=dna_brief,
        )):
            # Collect text from BOTH "log" and "message" events (agent output is "log" by default)
            event_type = evt.get("event")
            if event_type in ("log", "message"):
                data = json.loads(evt["data"]) if isinstance(evt.get("data"), str) else evt.get("data", {})
                text = data.get("text", "")
                if text:
                    collected_design_text.append(text)
            yield evt

    # ── BRAND AUTO-DETECT ──
    # If the user's description (or their plan) mentions a URL, scrape that
    # site's brand colours (logo via og:image → k-means) and stash on the
    # design_spec so save_design_spec's existing brand.derived override path
    # (commit e037bf2) takes precedence over LLM-extracted or industry-default
    # palettes. Failure is silent — generation must not break if the URL is
    # unreachable, has no og:image, or returns malformed bytes.
    brand_derived: dict | None = None
    try:
        import re as _re
        text_for_url = " ".join([
            description or "",
            (plan or {}).get("description") or "",
        ])
        m = _re.search(r"https?://[^\s\")>]+", text_for_url)
        if m:
            from services.url_brand_scraper import scrape_brand_from_url
            brand_url = m.group(0)
            yield sse_event("log", {"text": f"[Brand] Auto-detecting palette from {brand_url}"})
            scraped = await asyncio.to_thread(scrape_brand_from_url, brand_url)
            if scraped and getattr(scraped, "derived", None):
                # Normalise to a plain dict for JSON storage.
                d = scraped.derived
                brand_derived = {
                    "primary": d.primary, "secondary": d.secondary, "accent": d.accent,
                    "background": d.background, "surface": d.surface,
                    "text": d.text, "border": d.border,
                    "success": d.success, "warning": d.warning, "destructive": d.destructive,
                    "source_url": brand_url,
                }
                yield sse_event("log", {"text": f"[Brand] Extracted primary {d.primary} from {brand_url}"})
            else:
                yield sse_event("log", {"text": f"[Brand] Could not extract palette from {brand_url} — using LLM/industry defaults"})
    except Exception as _brand_exc:
        yield sse_event("log", {"text": f"[Brand] Auto-detect skipped: {_brand_exc}"})

    # Extract and save design spec
    if canonical_brief is not None:
        # Brief-canonical path — brief IS the sole design authority.
        # Skip DNA merge / industry-defaults / LLM parsing entirely.
        design_spec = brief_to_design_spec(canonical_brief)
        if brand_derived:
            design_spec.setdefault("brand", {})["derived"] = brand_derived
        save_design_spec(output_dir, design_spec, plan=plan)
        yield sse_event("log", {"text": (
            f"[Design] Brief-canonical spec saved — "
            f"brand {canonical_brief.palette.brand}, accent {canonical_brief.palette.accent}, "
            f"display '{canonical_brief.typography.display_family}'")})
    else:
        design_text = "\n".join(collected_design_text)
        design_spec = extract_design_spec(design_text)
        # Spec D W1 — brief is the stronger authority than DNA. If a
        # contracts/brief.json exists (default-on today), its
        # brief_to_design_spec form beats the DNA-derived merge base /
        # terminal fallback. DNA stays as fallback for old projects
        # generated before FORGE_BRIEF_AUTHOR landed.
        _fallback_brief = load_brief_from_disk(output_dir)
        if design_spec:
            # Merge a canonical base UNDER the agent's spec: agent values
            # win where present, base fills every gap — a partially-parsed
            # spec still yields a complete distinct identity instead of
            # silently reverting to defaults.
            try:
                from services.design_compiler import _merge_spec
                if _fallback_brief is not None:
                    base = brief_to_design_spec(_fallback_brief)
                    # When the brief carries an active visual_lock, its
                    # palette + typography are EXACT tokens the whole
                    # pipeline must honor (see services.visual_lock_presets
                    # docstring). Invert the merge so the brief overrides
                    # the LLM design agent instead of only filling gaps —
                    # otherwise a shadcn-blue LLM guess buries a locked
                    # trust-navy palette. When there is no lock, keep the
                    # original ordering: LLM creativity wins, brief fills.
                    _lock_active = bool(getattr(_fallback_brief, "visual_lock", None)
                                        and _fallback_brief.visual_lock.is_active())
                    if _lock_active:
                        design_spec = _merge_spec(design_spec, base)
                        logger.info(
                            "[design-merge] visual_lock=%s active → brief overrides LLM spec",
                            _fallback_brief.visual_lock.preset_name,
                        )
                    else:
                        design_spec = _merge_spec(base, design_spec)
                elif design_dna:
                    from services.design_dna import to_design_spec as _dna_spec
                    design_spec = _merge_spec(_dna_spec(design_dna), design_spec)
            except Exception:
                logger.exception("[Design] merge-base build failed (using raw spec)")
            if brand_derived:
                design_spec.setdefault("brand", {})["derived"] = brand_derived
            save_design_spec(output_dir, design_spec, plan=plan)
            yield sse_event("log", {"text": f"[Design] Design spec saved — theme: {design_spec.get('colorPalette', {}).get('primary', '?')}"})
        elif _fallback_brief is not None:
            # Fence-miss: prefer brief-derived spec over DNA-derived —
            # the brief is a real, authored contract; DNA is a heuristic.
            design_spec = brief_to_design_spec(_fallback_brief)
            if brand_derived:
                design_spec.setdefault("brand", {})["derived"] = brand_derived
            save_design_spec(output_dir, design_spec, plan=plan)
            yield sse_event("log", {"text": (
                f"[Design] Agent fence unparseable — using the project's design brief "
                f"(domain {_fallback_brief.identity.domain}, brand {_fallback_brief.palette.brand})")})
        elif design_dna:
            # Fence-miss + no brief on disk: the DNA IS a complete, distinct,
            # valid design — vastly better than the generic industry defaults
            # that used to land here.
            from services.design_dna import to_design_spec as _dna_spec
            design_spec = _dna_spec(design_dna)
            if brand_derived:
                design_spec.setdefault("brand", {})["derived"] = brand_derived
            save_design_spec(output_dir, design_spec, plan=plan)
            yield sse_event("log", {"text": (
                f"[Design] Agent fence unparseable — using the project's design DNA "
                f"({design_dna['archetype']}, primary {design_dna['color']['primary']})")})
        else:
            from services.industry_design import generate_design_spec_from_industry, generate_css_variables_from_spec
            design_spec = generate_design_spec_from_industry(
                domain_label, description, plan, domain_context=domain_ctx,
            )
            if brand_derived:
                design_spec.setdefault("brand", {})["derived"] = brand_derived
            save_design_spec(output_dir, design_spec, plan=plan)
            primary = design_spec.get("colorPalette", {}).get("primary", "?")
            palette_char = (domain_ctx or {}).get("visualLanguage", {}).get("paletteCharacter") if isinstance(domain_ctx, dict) else None
            suffix = f" (palette: {palette_char})" if palette_char else ""
            yield sse_event("log", {"text": f"[Design] Using industry defaults for {domain_label}{suffix} — primary: {primary}"})

    # Design template — if the user picked a look before generation, seed it over
    # whatever the design agent/industry defaults produced (template wins on visuals).
    try:
        from services.design_template_store import load_selection
        from services.design_templates import seed_design_spec
        _sel_tpl = load_selection(output_dir)
        if _sel_tpl:
            design_spec = seed_design_spec(design_spec, _sel_tpl)
            save_design_spec(output_dir, design_spec, plan=plan)
            yield sse_event("log", {"text": f"[Design] Applied selected template: {_sel_tpl.get('name')}"})
    except Exception as _tpl_exc:
        yield sse_event("log", {"text": f"[Design] Template seeding skipped: {_tpl_exc}"})

    # Inject register classification into design-spec so downstream agents can read it.
    # The async classifier asks Sonnet to choose one of six registers from the brief +
    # domain + entity shape — the rule-based heuristic falls back to "workday" too
    # aggressively when keywords don't match. On failure (no API key, parse error,
    # timeout), the LLM helper transparently falls through to the rule-based classifier.
    # Always set register + cta_hierarchy unconditionally so both fields are in sync
    # regardless of whether the LLM happened to include a "register" field already.
    from agents.planner import classify_register_llm
    from services.cta_defaults import defaults_for_register as _defaults_for_register
    # SINGLE AUTHORITY: the design DNA's skin decides the register (component
    # variant set). The old flow ran a SECOND classifier here on a worse brief
    # and fell back to "workday" so often that a healthcare app and a
    # pet-matchmaking app both shipped identical workday chrome (audited).
    register = ((design_dna or {}).get("register")
                or plan.get("register")
                or await classify_register_llm(
                    description, plan.get("domain", ""), plan))
    if design_spec is not None:
        design_spec["register"] = register
        design_spec["cta_hierarchy"] = _defaults_for_register(register)
        save_design_spec(output_dir, design_spec, plan=plan)
        yield sse_event("log", {"text": f"[Design] Register: {register}"})

    # UX spec is now part of the comprehensive design-spec produced by the Design Agent.
    # Component and page agents read src/contracts/design-spec.json directly.
    yield sse_event("log", {"text": f"[Design] Domain: {domain_label} — design spec covers colors, typography, spacing, layout, UX patterns, navigation, compliance"})

    # --- Compile design-spec → tokens.custom.json ---
    # This runs deterministically (no LLM), so it's fast and idempotent.
    # Schema agents that fire after this point see project-tuned tokens.
    # Task 36: gated behind FIDELITY_MODE_ENABLED flag.
    if FIDELITY_MODE_ENABLED:
        try:
            from services.design_compiler import compile_to_file
            spec_path = Path(output_dir) / "src" / "contracts" / "design-spec.json"
            if spec_path.exists():
                design_spec_for_tokens = json.loads(spec_path.read_text())
                tokens_path = Path(output_dir) / "src" / "theme" / "tokens.custom.json"
                compile_to_file(design_spec_for_tokens, str(tokens_path))
                yield sse_event("log", {"text": f"[Tokens] ✓ Compiled tokens.custom.json from design-spec"})
            else:
                yield sse_event("log", {"text": f"[Tokens] No design-spec.json found at {spec_path}; skipping compile"})
        except Exception as e:
            logger.exception("[Tokens] design_compiler failed")
            yield sse_event("log", {"text": f"[Tokens] ⚠ Compile failed (non-fatal): {e}"})
    else:
        yield sse_event("log", {"text": "[Tokens] FIDELITY_MODE_ENABLED=false — skipping design_compiler step"})

    # DNA-aware recompile: merge the project's design DNA under the saved spec
    # so tokens.custom.json is COMPLETE (personality knobs included) even when
    # the agent spec was partial. Also runs when FIDELITY_MODE gated the block
    # above off — per-app tokens are foundational identity, not a fidelity
    # extra; skipping them was a guaranteed-sameness path.
    if design_dna is not None:
        try:
            from services.design_compiler import compile_to_file as _ctf
            _spec_path = Path(output_dir) / "src" / "contracts" / "design-spec.json"
            _spec_for_tokens = json.loads(_spec_path.read_text()) if _spec_path.exists() else {}
            _tokens_path = Path(output_dir) / "src" / "theme" / "tokens.custom.json"
            _ctf(_spec_for_tokens, str(_tokens_path), dna=design_dna)
            yield sse_event("log", {"text": "[Tokens] ✓ DNA-merged tokens.custom.json compiled"})
        except Exception as _dna_ct_exc:
            logger.exception("[Tokens] DNA-aware compile failed")
            yield sse_event("log", {"text": f"[Tokens] ⚠ DNA compile failed (non-fatal): {_dna_ct_exc}"})

    # Make the design identity visible to EVERY downstream page author:
    # page_schema_agent reads plan["design_spec"] and the schema-prompt builder
    # reads plan["_output_dir"] — neither was ever set, so the design brief /
    # register exemplars were silently disabled on the LLM page path.
    if design_spec is not None:
        plan["design_spec"] = design_spec
    plan["_output_dir"] = output_dir

    # Phase 1: Contract generation — deterministic builder is PRIMARY, LLM is FALLBACK.
    yield sse_event("status", {"message": "Generating contracts..."})
    for aid in PHASE_TO_AGENTS["contract"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["contract"]))

    from services.contract_generator import generate_contracts
    from services.phase_gates import check_contract_completeness
    try:
        _cg = generate_contracts(output_dir, plan)
        yield sse_event("log", {"text": f"[Contract] deterministic: {len(_cg.get('generated', []))} file(s), {len(_cg.get('errors', []))} error(s)"})
    except Exception as _cgx:
        yield sse_event("log", {"text": f"[Contract] deterministic generation failed (falling back to LLM): {_cgx}"})

    _contract_precheck = check_contract_completeness(output_dir, plan)
    if _contract_precheck["passed"]:
        yield sse_event("log", {"text": "[Contract] deterministic contracts complete — skipping LLM agent"})
    else:
        async for evt in _stream_phase("Contract", run_contract_agent(output_dir, plan, domain_context=domain_ctx)):
            yield evt
    for aid in PHASE_TO_AGENTS["contract"]:
        yield sse_event("office", agent_complete_event(aid))

    # --- CONTRACT GATE: verify contracts cover every entity from plan ---
    contract_gate = check_contract_completeness(output_dir, plan)
    if not contract_gate["passed"]:
        gap_count = len(contract_gate["missing"])
        yield sse_event("log", {"text": f"[Contract Gate] {gap_count} gaps found — sending back to contract agent"})
        yield sse_event("status", {"message": f"Completing contracts ({gap_count} gaps)..."})
        try:
            async for evt in _stream_phase("Contract-Fix", run_contract_agent(output_dir, plan, domain_context=domain_ctx)):
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
        from services.contract_generator import ensure_approval_bindings
        _eb = ensure_approval_bindings(output_dir, plan)
        if _eb["added"]:
            yield sse_event("log", {"text": f"[Contract] approval start-bindings: added {_eb['added']} <entity>_created binding(s)"})
    except Exception as _ebx:
        yield sse_event("log", {"text": f"[Contract] approval-binding patch skipped: {_ebx}"})

    # Handoff: contract → schema
    yield sse_event("office", agent_handoff_event("contract_writer", "schema_designer", artifact="contracts"))

    # Phase 2: Schema + config + types + npm install
    yield sse_event("status", {"message": "Building foundation (schema, config, types)..."})
    _cf = chat_flavor.start("data")
    if _cf:
        yield sse_event("message", {"text": _cf})
    for aid in PHASE_TO_AGENTS["schema"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["schema"]))
    project_short_id = Path(output_dir).name

    # Deterministic Drizzle schema + types builder is PRIMARY, LLM is FALLBACK.
    from services.schema_builder import build_schema_files
    try:
        _sb = build_schema_files(plan, output_dir)
        yield sse_event("log", {"text": f"[Schema] deterministic: {len(_sb.get('generated', []))} file(s), {len(_sb.get('errors', []))} error(s)"})
    except Exception as _sbx:
        yield sse_event("log", {"text": f"[Schema] deterministic generation failed (falling back to LLM): {_sbx}"})

    if _schema_files_complete(output_dir, plan):
        yield sse_event("log", {"text": "[Schema] deterministic schema complete — skipping LLM agent"})
    else:
        async for evt in _stream_phase("Schema", run_schema_agent(output_dir, plan, domain_context=domain_ctx, project_short_id=project_short_id)):
            yield evt
    for aid in PHASE_TO_AGENTS["schema"]:
        yield sse_event("office", agent_complete_event(aid))

    # Registry: extract actual schema entities
    extracted_entities = extract_entities_from_schema(output_dir)
    if extracted_entities:
        registry = reconcile_entities(registry, extracted_entities)
        save_registry(output_dir, registry)
        yield sse_event("log", {"text": f"[Registry] Updated entities from schema: {len(extracted_entities)} extracted"})
        _cf = chat_flavor.done("data", len(extracted_entities))
        if _cf:
            yield sse_event("message", {"text": _cf})

    # Correct the CANONICAL registry (contracts/resource-registry.json, read by
    # the page/schema agents) against the real emitted schema — its plan-derived
    # notNull/enum drift otherwise (see registry_schema_reconcile).
    try:
        _rc = reconcile_registry_to_schema(output_dir)
        logger.info(
            "resource-registry reconciled to schema: %d entities, %d columns",
            _rc["entities_reconciled"], _rc["columns_updated"],
        )
    except Exception:
        logger.exception("resource-registry schema reconcile failed (non-fatal)")

    # Deliverable previews — data models (drives the live tracker + preview cards).
    try:
        from services.progress_events import iter_entities as _iter_entities
        for _rev in _iter_entities(output_dir):
            yield sse_event("resource", _rev)
    except Exception:
        pass

    # Handoff: schema → parallel agents
    yield sse_event("office", agent_handoff_event("schema_designer", "api_generator", artifact="schema.prisma"))

    # Phase 3: Business logic only (domain workflows + service routes).
    # Entity CRUD is NO LONGER generated per-entity — it's served by the single
    # Data Engine catch-all (/api/data/[...path], injected below), which does
    # owner-FK defaulting, column filtering and rules validation. The old
    # per-entity API agent + deterministic CRUD fill only produced raw-Drizzle
    # routes that duplicated — and worse, *shadowed* — the engine, so they've been
    # dropped (a redundant LLM phase removed; see services/api_route_prune.py).
    parallel_agents: list[tuple[str, any]] = []
    parallel_agent_ids: list[str] = []

    # Deterministic-first: skip the ~4-min BusinessLogic LLM agent up front. Workflows
    # are built deterministically from the plan + real schema below (executable), and
    # the executability guard LLM-repairs only the steps it couldn't infer.
    if plan.get("workflows") and not _deterministic_workflows():
        yield sse_event("status", {"message": "Generating business logic (domain workflows + services)..."})
        _cf = chat_flavor.start("workflows")
        if _cf:
            yield sse_event("message", {"text": _cf})
        parallel_agents.append(
            ("BusinessLogic", lambda: run_business_logic_agent(output_dir, plan, domain_context=domain_ctx))
        )
        parallel_agent_ids.append("bizlogic_agent")
        yield sse_event("office", agent_handoff_event("schema_designer", "bizlogic_agent", artifact="schema.prisma"))

    if parallel_agents:
        yield sse_event("office", parallel_start_event(parallel_agent_ids))
        for aid in parallel_agent_ids:
            phase_key = {"api_generator": "api", "bizlogic_agent": "business_logic"}.get(aid, "business_logic")
            yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM[phase_key]))

        async for evt in run_parallel_agents(output_dir, parallel_agents):
            if evt.get("event") == "agent_result":
                data = json.loads(evt["data"])
                total_cost += data.get("cost_usd", 0)
                total_turns += data.get("num_turns", 0)
                total_duration += data.get("duration_ms", 0)
            else:
                yield evt

        for aid in parallel_agent_ids:
            yield sse_event("office", agent_complete_event(aid))

        if plan.get("workflows"):
            _cf = chat_flavor.done("workflows", len(plan.get("workflows") or []))
            if _cf:
                yield sse_event("message", {"text": _cf})

    # Registry: extract actual API routes
    extracted_routes = extract_routes_from_files(output_dir)
    if extracted_routes:
        registry = merge_section(registry, "api_routes", extracted_routes)
        save_registry(output_dir, registry)
        yield sse_event("log", {"text": f"[Registry] Updated routes: {len(extracted_routes)} extracted"})

    # Validate registry after schema + routes
    reg_errors = validate_registry(registry)
    if reg_errors:
        report = format_validation_report(reg_errors)
        yield sse_event("log", {"text": f"[Registry] {report}"})
        yield sse_event("registry_validation", {"phase": "post_api", "errors": [{"section": e.section, "name": e.name, "error": e.error, "suggestion": e.suggestion, "severity": e.severity} for e in reg_errors]})

    # Handoff: parallel agents → components/IR
    yield sse_event("office", agent_handoff_event("api_generator", "component_builder", artifact="api_routes"))

    # --- RULES AGENT: convert planner prose into structured ProjectRules ---
    # Runs before runtime injection so the runtime_injector exports them
    # as rules/index.json. Also syncs to the project_rules DB table when a
    # project_id is available so the editor UI's RulesPanel picks them up.
    # Failures are non-fatal (rules stay empty).
    try:
        from agents.rules_agent import run_rules_agent
        yield sse_event("status", {"message": "Generating business rules..."})
        rules = await run_rules_agent(
            output_dir, plan, domain_context=domain_ctx, project_id=project_id,
        )
        suffix = " (synced to DB)" if project_id is not None and rules else ""
        yield sse_event("log", {"text": f"[Rules] Generated {len(rules)} rule(s) from planner intent{suffix}"})
    except Exception as e:
        logger.exception("[Rules] agent failed")
        yield sse_event("log", {"text": f"[Rules] ⚠ Generation failed (non-fatal): {e}"})

    # --- AUTH GATE: verify auth layer is complete (most critical gate) ---
    from services.phase_gates import check_auth_completeness
    auth_gate = check_auth_completeness(output_dir)
    if not auth_gate["passed"]:
        issue_count = len(auth_gate["issues"])
        yield sse_event("log", {"text": f"[Auth Gate] {issue_count} auth issues — sending back to auth agent"})
        yield sse_event("status", {"message": f"Fixing auth layer ({issue_count} issues)..."})
        try:
            # Auth handled by templates — re-copy if missing
            template_dir = Path(__file__).parent.parent / "templates" / "app-foundation"
            for auth_file in ["src/auth.ts", "src/middleware.ts", "src/app/api/auth/[...nextauth]/route.ts", "src/app/api/auth/signup/route.ts"]:
                src = template_dir / auth_file
                dst = Path(output_dir) / auth_file
                if src.exists() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    # `shutil` is imported at the top of this function.
                    shutil.copy2(src, dst)
            # Yield a dummy event to satisfy the async for
            async for evt in _stream_phase("Auth-Fix", _empty_stream()):
                yield evt
            yield sse_event("log", {"text": "[Auth Gate] Auth fix complete"})
        except Exception as e:
            yield sse_event("log", {"text": f"[Auth Gate] Fix attempt failed: {e}"})
    else:
        yield sse_event("log", {"text": "[Auth Gate] ✓ Auth layer complete"})

    # --- RUNTIME INJECTION: Data Engine + Workflow Engine + Rules Engine ---
    # Always inject — Data Engine handles ALL entity CRUD, Workflow Engine handles business processes.
    try:
        from services.runtime_injector import inject_runtime
        rt_result = inject_runtime(output_dir, app_name=(plan.get("appName") or plan.get("module_name") or plan.get("name")), domain=plan.get("domain"), project_id=str(project_id) if project_id else None)
        rt_copied = len(rt_result.get("copied", []))
        rt_errors = len(rt_result.get("errors", []))
        yield sse_event("log", {
            "text": f"[Runtime] Injected Data Engine + Workflow Engine: "
                    f"{rt_copied} files copied"
                    + (f", {rt_errors} errors" if rt_errors else "")
        })
        if rt_errors:
            for err in rt_result["errors"]:
                yield sse_event("log", {"text": f"[Runtime] Error: {err}"})
    except Exception as e:
        yield sse_event("log", {"text": f"[Runtime] Injection failed: {e}"})

    # --- INTEGRATIONS SYNC: platform → .env.local -----------------------------
    # runtime_injector lays down mcpClientPool.ts + integrations resolver.ts,
    # but the credentials themselves come from the org's platform_integrations
    # + platform_mcp_servers rows. Run env_writer once so the generated app
    # starts up with every enabled MCP server + integration key already wired.
    # Without this, an app declaring EXTERNALS (e.g. visual-product-search →
    # Firecrawl) generates with a broken pool config until someone manually
    # clicks Sync on the platform settings page. Non-fatal.
    if project_id is not None:
        try:
            from database import async_session
            from models.project import Project
            from services.env_writer import write_env_local_from_platform
            async with async_session() as _db:
                _proj = await _db.get(Project, project_id)
                if _proj is not None and _proj.org_id is not None:
                    _iw = await write_env_local_from_platform(output_dir, _proj.org_id, _db)
                    _keys = _iw.get("set", []) or []
                    _mcp_n = _iw.get("mcp_servers", 0)
                    if _keys or _mcp_n:
                        yield sse_event("log", {
                            "text": (
                                f"[Integrations] Synced .env.local: "
                                f"{len(_keys)} key(s), {_mcp_n} MCP server(s)"
                            )
                        })
                    else:
                        yield sse_event("log", {
                            "text": "[Integrations] No platform integrations configured for org — .env.local unchanged"
                        })
        except Exception as e:
            yield sse_event("log", {"text": f"[Integrations] Sync skipped: {e}"})

    # --- PRUNE per-app artifacts that bypass the injected runtime engines ---
    # The Data Engine catch-all (/api/data/[...path]) serves ALL entity CRUD, and the
    # workflow engine (+ standard /api/workflows API) is the single path for domain
    # logic. Delete anything the BusinessLogic agent left that bypasses them:
    #   • per-entity CRUD routes (bare /api/<entity>/* and the SHADOWING /api/data/<entity>/*)
    #   • per-entity domain-action routes (/api/<entity>/[id]/approve|reject|review|advance)
    #   • imperative TS services under src/services/*.ts
    # The catch-all, auth, and standard workflow infra routes are preserved.
    try:
        from services.api_route_prune import prune_entity_crud_routes
        pruned = prune_entity_crud_routes(output_dir)
        if pruned["deleted"] or pruned["deleted_actions"] or pruned["deleted_services"]:
            yield sse_event("log", {"text": f"[API] pruned {len(pruned['deleted'])} CRUD route(s), {len(pruned['deleted_actions'])} bypass action-route(s), {len(pruned['deleted_services'])} TS service(s) → engines are the single execution path (CRUD + workflow)"})
        # Re-extract so the registry reflects the pruned tree (catch-all + actions).
        extracted_routes = extract_routes_from_files(output_dir)
        if extracted_routes:
            registry = merge_section(registry, "api_routes", extracted_routes)
            save_registry(output_dir, registry)
    except Exception as e:
        yield sse_event("log", {"text": f"[API] route prune skipped: {e}"})

    # --- API GATE: the Data Engine catch-all must exist (it serves ALL entity CRUD) ---
    _catch_all = Path(output_dir) / "src" / "app" / "api" / "data" / "[...path]" / "route.ts"
    if _catch_all.exists():
        yield sse_event("log", {"text": "[API Gate] ✓ Data Engine catch-all present (serves all entity CRUD)"})
    else:
        yield sse_event("log", {"text": "[API Gate] ⚠ Data Engine catch-all missing — re-injecting runtime"})
        try:
            from services.runtime_injector import inject_runtime as _reinject
            # Pass project_id so the rules re-export reads the project_rules DB
            # (manual/editor rules live ONLY there) instead of registry-only —
            # otherwise this recovery path silently strips every hand-authored
            # rule from an app that had them.
            _reinject(output_dir, app_name=(plan.get("appName") or plan.get("module_name") or plan.get("name")), domain=plan.get("domain"), project_id=project_id)
        except Exception as e:
            yield sse_event("log", {"text": f"[API Gate] catch-all re-injection failed: {e}"})

    # --- Deterministic CRUD workflows (BEFORE the frontend/binding phase) ---
    # Create/Update/Delete<Entity> must exist on disk before run_schema_frontend_
    # pipeline binds action buttons, so the binding pass can wire Delete/New/Edit
    # and Form submit to real workflows. (The block further below runs only in
    # the legacy non-schema path; this one covers the default schema path and is
    # idempotent — it never clobbers the bizlogic domain workflows.)
    try:
        from services.crud_workflow_generator import generate_crud_workflows
        _crud_plan = plan if (plan or {}).get("entities") else {"entities": (registry or {}).get("entities") or {}}
        _crud_written = generate_crud_workflows(_crud_plan, output_dir)
        if _crud_written:
            yield sse_event("log", {"text": f"[CRUD] generated {len(_crud_written)} workflow(s): {', '.join(_crud_written[:6])}"})
    except Exception as _crud_ex:
        yield sse_event("log", {"text": f"[CRUD] generation skipped: {_crud_ex}"})

    # Deliverable previews — workflows (domain workflows first, then CRUD rollup).
    try:
        from services.progress_events import iter_workflows as _iter_workflows
        for _rev in _iter_workflows(output_dir):
            yield sse_event("resource", _rev)
    except Exception:
        pass

    # Binding contract — with the real DB entities + all workflows now on disk,
    # derive the EXACT bindings from reality (FK dropdowns → real target entity +
    # slug + label, form → real Create/Update workflow) and persist them, so the
    # page agent is handed reality instead of guessing short entity names.
    try:
        from services.binding_contract import save_binding_contract
        _bc = save_binding_contract(output_dir)
        _fk_total = sum(len(v.get("fkBindings") or []) for v in _bc.values())
        yield sse_event("log", {"text": f"[Contract] Derived binding contract for {len(_bc)} entities ({_fk_total} FK bindings)"})
    except Exception as _bc_ex:
        yield sse_event("log", {"text": f"[Contract] Binding contract skipped: {_bc_ex}"})

    # --- Phase 4+5: Frontend generation (Schema path, IR path, or LLM path) ---
    from services.schema_pipeline import SCHEMA_MODE_ENABLED, run_schema_frontend_pipeline
    from services.ir_pipeline import IR_FRONTEND_ENABLED, run_ir_frontend_pipeline

    if SCHEMA_MODE_ENABLED:
        # ── SCHEMA PATH: emit JSON Page schemas (Phase 4) ──
        yield sse_event("status", {"message": "Generating frontend via schema agent..."})
        # IRF-M5-T4 wire: preview stage intent from stage_plan authors so
        # the frontend can render a StagePlanChip before the LLM output
        # starts. Silent when no ambient SessionContext is set.
        try:
            from services.stage_plan_emitter import preview as _sp_preview
            _sp = _sp_preview("page_schema_agent")
            if _sp.get("intent"):
                yield sse_event("stage_plan", _sp)
        except Exception:  # noqa: BLE001
            pass
        # Recalibrate baselines using the plan's real counts so the ring
        # + ETA reflect the *actual* frontend_schema cost — a 30-page app
        # is not a 120s phase. Silent no-op if counts are missing.
        try:
            _plan_pages_n = len(plan.get("pages") or [])
            _plan_entities_n = len(plan.get("entities") or [])
            _plan_workflows_n = len(plan.get("workflows") or [])
            _plan_parallelism = int(os.getenv("FORGE_PAGE_CONCURRENCY", "5") or "5")
            _progress.recalibrate(
                pages=_plan_pages_n,
                entities=_plan_entities_n,
                workflows=_plan_workflows_n,
                parallelism=_plan_parallelism,
            )
            for _pe in _drain_progress():
                yield _pe
        except Exception:
            pass
        _progress.phase_start("frontend_schema")
        for _pe in _drain_progress():
            yield _pe
        yield sse_event("log", {"text": "[Pipeline] Using schema-mode (default — Phase 4)"})

        # ── PB-2: Product brief synthesis (behind FORGE_PRODUCT_BRIEF) ────
        # The product brief is the missing input for beautiful-app generation
        # (Path B commitment). Deterministically derived from plan.actors +
        # plan.journeys + design_brief — no LLM call in the primary path.
        # Downstream consumers (shell frame picker, nav-flow emitter, empty-
        # state authoring) read the persisted brief. Best-effort — a
        # synthesis failure never blocks generation.
        _product_brief = None
        try:
            from services.product_brief import (
                derive_from_plan as _derive_pb,
                is_product_brief_enabled as _pb_on,
                save_product_brief as _save_pb,
            )
            # Unconditional entry log — silent skips (env=off) were
            # invisible in prior runs. Now we always know whether the
            # gate opened or closed and why.
            _pb_flag = _pb_on()
            logger.info("[ProductBrief] block reached — _pb_on()=%s", _pb_flag)
            if _pb_flag:
                # Reuse the already-loaded design brief when present so voice
                # notes carry through. `_brief_for_dna` was set upstream in
                # the design_dna block; fall back to disk if it's absent.
                _brief_for_pb = locals().get("_brief_for_dna")
                if _brief_for_pb is None:
                    try:
                        from services.design_brief_to_prompt import load_brief_from_disk as _load_brief
                        _brief_for_pb = _load_brief(output_dir)
                    except Exception:
                        _brief_for_pb = None
                _product_brief = _derive_pb(plan, design_brief=_brief_for_pb)
                _save_pb(output_dir, _product_brief)
                _persona_count = len(_product_brief.personas)
                yield sse_event("log", {
                    "text": f"[ProductBrief] ✓ {_persona_count} personas · "
                            f"archetype={_product_brief.archetype or 'unspec'} → product-brief.json"
                })
        except Exception as _pb_exc:  # noqa: BLE001 — never block generation
            # Log to backend log so silent failures are diagnosable.
            # SSE alone is invisible in a log tail and hides the traceback.
            logger.exception("[ProductBrief] synthesis failed — SL2 chain will no-op")
            yield sse_event("log", {"text": f"[ProductBrief] ⚠ synthesis failed: {_pb_exc}"})

        # ── NEW: nav-flow + shell layout (before per-page schema generation) ──
        # Build nav-flow.json from plan.pages first so the shell agent knows
        # which routes are shell pages vs auth pages.
        _nav_flow: dict | None = None
        try:
            from services.nav_flow_from_plan import nav_flow_from_plan, write_nav_flow
            yield sse_event("log", {"text": "[NavFlow] building from plan"})
            # PB-4: pass product brief so nav-flow can attach personas
            # (top-level pill labels + per-persona job groupings). When
            # the brief is None, nav_flow_from_plan behaves exactly as
            # before — backward-compatible.
            _nav_flow = nav_flow_from_plan(plan, product_brief=_product_brief)
            write_nav_flow(output_dir, _nav_flow)
            _nf_page_count = len(_nav_flow.get("pages", []))
            yield sse_event("log", {"text": f"[NavFlow] ✓ {_nf_page_count} pages → nav-flow.json"})
        except Exception as _nf_exc:
            yield sse_event("log", {"text": f"[NavFlow] ⚠ nav-flow build failed: {_nf_exc}"})

        # Run shell_layout_agent only when there are shell:true pages (skip for
        # auth-only projects — they need no persistent chrome).
        _shell_pages = [p for p in (_nav_flow or {}).get("pages", []) if p.get("shell")]
        if not _shell_pages:
            yield sse_event("log", {"text": "[ShellLayout] skipped — no shell:true pages in plan"})
        else:
            yield sse_event("log", {"text": "[ShellLayout] generating app shell"})
            try:
                from agents.shell_layout_agent import generate_shell_to_file as _gen_shell

                # Collect brand info from design_spec (already computed above)
                from services.runtime_injector import _resolve_app_name
                _brand: dict | None = None
                if design_spec:
                    _palette = design_spec.get("colorPalette", {})
                    _brand = {
                        # shell_templates reads "primaryColor"/"secondaryColor" —
                        # the bare "primary" key was dead code (brand color never
                        # steered the shell accent). Keep both for compat.
                        "primaryColor": _palette.get("primary"),
                        "secondaryColor": _palette.get("secondary"),
                        "primary": _palette.get("primary"),
                        "secondary": _palette.get("secondary"),
                        # SAME resolver the login uses (__APP_NAME__): a
                        # distinct user-given name wins; a generic/vertical
                        # name ("DietPlanner", "legaltech") falls through to
                        # the DNA's seeded brand. Keeps the rail and the
                        # sign-in screen telling one story.
                        "appName": _resolve_app_name(
                            Path(output_dir),
                            plan.get("name") or plan.get("app_name"),
                            plan.get("domain")),
                        "logoUrl": design_spec.get("logoUrl"),
                    }

                _shell = await _gen_shell(
                    output_dir=output_dir,
                    plan=plan,
                    nav_flow=_nav_flow,
                    brand=_brand,
                    domain_context=domain_ctx,
                    design_spec=design_spec,
                )
                if _shell is None:
                    yield sse_event("log", {"text": "[ShellLayout] ⚠ agent produced no parseable schema — pages will render bare"})
                else:
                    def _count_nodes(n: dict) -> int:
                        if not isinstance(n, dict):
                            return 0
                        return 1 + sum(_count_nodes(c) for c in (n.get("children") or []))
                    _n_nodes = sum(_count_nodes(c) for c in _shell.get("children", []))
                    yield sse_event("log", {"text": f"[ShellLayout] ✓ shell.json written ({_n_nodes} nodes)"})
            except Exception as _shell_exc:
                yield sse_event("log", {"text": f"[ShellLayout] ⚠ failed: {_shell_exc} — pages will render bare"})
        # ── END: nav-flow + shell layout ─────────────────────────────────────

        # Part A — skip auth routes from data-schema generation so the LLM
        # does NOT generate dashboard schemas for /login and /signup.
        _auth_routes = {
            p.get("route")
            for p in (plan.get("pages") or [])
            if isinstance(p, dict)
            and (p.get("type") or "").lower() == "auth"
            and p.get("route")
        }

        try:
            async for evt in run_schema_frontend_pipeline(
                output_dir, plan, description, domain_context=domain_ctx,
                skip_routes=_auth_routes if _auth_routes else None,
            ):
                yield evt
        except Exception as e:
            import traceback
            logger.exception("[Pipeline] Schema pipeline failed: %s", e)
            yield sse_event("log", {"text": f"[Pipeline] ⚠ Schema pipeline error: {e}"})
            yield sse_event("log", {"text": f"[Pipeline] Traceback: {traceback.format_exc()[:500]}"})

        # IRF-M5-T4 wire: append an EditRecord for the completed schema
        # stage — the ambient SessionContext already has each page's
        # per-attempt verify records (from stage_verify_ladder); this
        # adds the stage-level "what got produced" summary Smith sees
        # via session_history.edit_history.
        try:
            from services.stage_plan_emitter import record_after as _sp_record_after
            _sp_record_after("page_schema_agent", reason="pipeline run")
        except Exception:  # noqa: BLE001
            pass

        # Part B — deterministically emit real auth-page form schemas so the
        # preview shows a login/signup form, not a data dashboard stub.
        try:
            from services.auth_page_schema import emit_auth_page_schemas
            _auth_written = emit_auth_page_schemas(output_dir, plan)
            if _auth_written:
                yield sse_event("log", {"text": f"[Auth] wrote real form schemas: {sorted(_auth_written)}"})
        except Exception as _auth_ex:
            yield sse_event("log", {"text": f"[Auth] auth-schema emit skipped: {_auth_ex}"})

        # --- CTA HIERARCHY GATE: detect + log only (no retry loop yet) ---
        try:
            from services.phase_gates import check_cta_hierarchy
            cta_gate = check_cta_hierarchy(output_dir, plan)
            if not cta_gate["passed"]:
                yield sse_event("log", {
                    "text": f"[CTA Gate] {len(cta_gate['issues'])} issues — flagging only (no auto-retry in this iteration)"
                })
                for issue in cta_gate["issues"][:10]:
                    yield sse_event("log", {"text": f"[CTA Gate]   - {issue}"})
            else:
                yield sse_event("log", {"text": "[CTA Gate] ✓ All schemas satisfy CTA hierarchy"})
        except Exception as e:
            yield sse_event("log", {"text": f"[CTA Gate] check failed: {e}"})

        # --- PROGRESSIVE DISCLOSURE GATE: detect + log only (matches CTA scope) ---
        try:
            from services.phase_gates import check_progressive_disclosure
            pd_gate = check_progressive_disclosure(output_dir, plan)
            if not pd_gate["passed"]:
                yield sse_event("log", {
                    "text": f"[PD Gate] {len(pd_gate['issues'])} issues — flagging only (no auto-retry in this iteration)"
                })
                for issue in pd_gate["issues"][:10]:
                    yield sse_event("log", {"text": f"[PD Gate]   - {issue}"})
            else:
                yield sse_event("log", {"text": "[PD Gate] ✓ All forms satisfy progressive disclosure"})
        except Exception as e:
            yield sse_event("log", {"text": f"[PD Gate] check failed: {e}"})

        # --- COVERAGE GATE: every plan.pages route must have a schema on disk ---
        try:
            from services.phase_gates import check_pages_coverage
            cov = check_pages_coverage(output_dir, plan)
            if not cov["passed"]:
                yield sse_event("log", {
                    "text": f"[Coverage Gate] {len(cov['missing'])} page(s) missing schema: {cov['missing']}"
                })
            else:
                yield sse_event("log", {"text": "[Coverage Gate] ✓ Every plan.pages route has a schema"})
        except Exception as e:
            yield sse_event("log", {"text": f"[Coverage Gate] check failed: {e}"})

        # Schema-mode skips QA/validator/indexer — they expect TSX artifacts.
        # Future Phase 6 work: schema-aware QA + validation.
        yield sse_event("log", {"text": "[Pipeline] Schema mode — skipping QA/validator/indexer (expect TSX artifacts)"})
        # Inject photoUrl / backgroundImage from design_spec.entityPhotos
        try:
            from services.post_emit_photo_injector import inject_photos_into_dir
            spec_path = Path(output_dir) / "src" / "contracts" / "design-spec.json"
            if spec_path.exists():
                spec = json.loads(spec_path.read_text())
                entity_photos = spec.get("entityPhotos") or {}
                if entity_photos:
                    n = inject_photos_into_dir(output_dir, entity_photos)
                    if n > 0:
                        yield sse_event("log", {"text": f"[Photos] Injected photo URLs into {n} page schema(s)"})
        except Exception as _ex:
            yield sse_event("log", {"text": f"[Photos] Injection skipped: {_ex}"})
        # Build nav-flow.json from plan.pages + transitions extracted from
        # the emitted schemas (photo injection has already finalised them).
        try:
            from services.nav_flow_emitter import emit_nav_flow
            emit_nav_flow(output_dir, plan)
            yield sse_event("log", {"text": "[NavFlow] nav-flow.json written"})
        except Exception as _nf_ex:
            yield sse_event("log", {"text": f"[NavFlow] Skipped: {_nf_ex}"})
        # Emit the standalone Next.js app skeleton so the project is
        # a runnable npm-install-able Next.js app. Idempotent — does
        # not overwrite the LLM-generated schemas / design-spec / globals.css.
        try:
            from services.app_emitter import emit_standalone_app
            from pathlib import Path as _P
            emit_standalone_app(output_dir=output_dir, project_short_id=_P(output_dir).name)
            yield sse_event("log", {"text": "[Emitter] Standalone Next.js app skeleton written"})
        except Exception as _emit_exc:
            yield sse_event("log", {"text": f"[Emitter] Skipped: {_emit_exc}"})
        # npm install off the LLM: the deterministic schema path skips the LLM
        # schema agent that used to run it. package.json now exists (emitter +
        # schema files written above), so install deps here. Idempotent.
        async for _npm_evt in _run_npm_install(output_dir):
            yield _npm_evt
        # Fidelity scoring still runs against the rendered scaffold — pages
        # exist as JSON schemas and the scaffold renders them live.
        try:
            async for evt in _stream_fidelity_scoring(output_dir, plan):
                yield evt
        except Exception as e:
            yield sse_event("log", {"text": f"[Fidelity] Pipeline skipped: {e}"})
        # Deterministic guard suite. Schema mode skips QA/validator/indexer (they
        # expect TSX), but post_generate_fixes operates on the JSON schemas + config
        # that schema mode DOES produce — check-constraint sql``, next.config jsdom
        # externalization, table row→detail nav, FK types/labels, border coherence,
        # CRUD-route/button wiring, etc. It was previously unreachable (the early
        # return below skipped it), so schema-mode apps shipped with every one of
        # those gaps. Run it here before finishing.
        try:
            _pgf_n = apply_post_generate_fixes(output_dir)
            yield sse_event("log", {"text": f"[Pipeline] post-generate guards applied ({_pgf_n} fix(es))"})
        except Exception as _pgf_ex:
            yield sse_event("log", {"text": f"[Pipeline] post-generate guards skipped: {_pgf_ex}"})
        # IRF-M5-T9: persist verify_history + edit_history so Smith turns
        # can consume them across sessions. Best-effort — a persistence
        # failure is telemetry loss, not a pipeline failure. The NameError
        # branch fires on the figma path when the T2-lite setup wasn't
        # threaded (harmless — it silently no-ops).
        try:
            from services.session_context import (
                current as _sc_current,
                persist_history as _sc_persist,
            )
            _sc_ctx_now = _sc_current()
            if _sc_ctx_now is not None:
                _sc_persist(_sc_ctx_now, output_dir)
        except Exception:  # noqa: BLE001
            pass
        yield sse_event("message", {"text": chat_flavor.ready()})
        _write_timing()
        _progress.finalize()
        for _pe in _drain_progress():
            yield _pe
        yield sse_event("log", {"text": f"[Timing] total: {sum(_phase_timings.values()):.1f}s — generation-timing.json written"})
        yield sse_event("office", build_success_event())
        yield sse_event("agent_result", {
            "num_turns": total_turns,
            "cost_usd": total_cost,
            "duration_ms": total_duration,
        })
        return
    elif IR_FRONTEND_ENABLED:
        # ── IR PATH: deterministic frontend generation ──
        yield sse_event("status", {"message": "Generating frontend via IR compiler..."})
        yield sse_event("log", {"text": "[Pipeline] Using IR frontend path (feature flag enabled)"})

        ir_cost = 0.0
        ir_turns = 0
        ir_duration = 0

        try:
            async for evt in run_ir_frontend_pipeline(
                output_dir, plan, description,
                domain_context=domain_ctx,
                figma_context=figma_context,
                project_id=str(project_id) if project_id else None,
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    ir_cost += data.get("cost_usd", 0)
                    ir_turns += data.get("num_turns", 0)
                    ir_duration += data.get("duration_ms", 0)
                else:
                    yield evt
        except Exception as e:
            logger.exception("[Pipeline] IR frontend pipeline failed: %s", e)
            yield sse_event("log", {
                "text": f"[Pipeline] ⚠ IR frontend pipeline error: {e}",
            })
            yield sse_event("log", {
                "text": f"[Pipeline] Traceback: {traceback.format_exc()[:500]}",
            })

        total_cost += ir_cost
        total_turns += ir_turns
        total_duration += ir_duration

        # Extract and register what the IR produced
        extracted_components = extract_components_from_files(output_dir)
        if extracted_components:
            registry = merge_section(registry, "components", extracted_components)
        extracted_pages = extract_pages_from_files(output_dir)
        if extracted_pages:
            registry = merge_section(registry, "pages", extracted_pages)
        save_registry(output_dir, registry)
    else:
        # ── LLM PATH: original agent-based frontend generation ──

        # Phase 4: Components
        yield sse_event("status", {"message": "Creating UI components..."})
        for aid in PHASE_TO_AGENTS["components"]:
            yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["components"]))
        async for evt in _stream_phase("Component", run_component_agent(output_dir, plan, domain_context=domain_ctx, design_spec=design_spec)):
            yield evt
        for aid in PHASE_TO_AGENTS["components"]:
            yield sse_event("office", agent_complete_event(aid))

        # Registry: extract actual components
        extracted_components = extract_components_from_files(output_dir)
        if extracted_components:
            registry = merge_section(registry, "components", extracted_components)
            save_registry(output_dir, registry)
            yield sse_event("log", {"text": f"[Registry] Updated components: {len(extracted_components)} extracted"})

        # --- COMPONENT GATE: verify all required components exist ---
        from services.phase_gates import check_component_completeness as _check_comp
        comp_gate = _check_comp(output_dir, plan)
        if not comp_gate["passed"]:
            comp_issue_count = len(comp_gate["issues"])
            yield sse_event("log", {"text": f"[Component Gate] {comp_issue_count} issues — sending back to component agent"})
            yield sse_event("status", {"message": f"Completing components ({comp_issue_count} issues)..."})
            try:
                async for evt in _stream_phase("Component-Fix", run_component_agent(output_dir, plan, domain_context=domain_ctx, design_spec=design_spec)):
                    yield evt
                extracted_components = extract_components_from_files(output_dir)
                if extracted_components:
                    registry = merge_section(registry, "components", extracted_components)
                    save_registry(output_dir, registry)
            except Exception as e:
                yield sse_event("log", {"text": f"[Component Gate] Fix attempt failed: {e}"})
        else:
            yield sse_event("log", {"text": "[Component Gate] ✓ All components complete"})

        # Handoff: components → pages
        yield sse_event("office", agent_handoff_event("component_builder", "page_assembler", artifact="components"))

        # Phase 5: Pages + layouts
        yield sse_event("status", {"message": "Building pages and layouts..."})
        for aid in PHASE_TO_AGENTS["pages"]:
            yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["pages"]))
        # Pages via per-page Anthropic-SDK generation (reliable, ~seconds each) instead of
        # the monolithic bundled-CLI page agent, which crawls under the auth throttle.
        # fill_missing_pages generates each page individually on the SDK, with a
        # deterministic minimal floor for any the LLM can't produce.
        from services.page_completeness import fill_missing_pages
        _pggen = await fill_missing_pages(output_dir, plan, domain_context=domain_ctx)
        yield sse_event("log", {"text": f"[Pages] generated {len(_pggen['llm'])} via per-page SDK, {len(_pggen['minimal'])} minimal floor"})
        # Deliverable previews — pages (route + notable components + node count).
        try:
            from services.progress_events import iter_pages as _iter_pages
            for _rev in _iter_pages(output_dir):
                yield sse_event("resource", _rev)
        except Exception:
            pass
        for aid in PHASE_TO_AGENTS["pages"]:
            yield sse_event("office", agent_complete_event(aid))

        # Registry: extract actual pages
        extracted_pages = extract_pages_from_files(output_dir)
        if extracted_pages:
            registry = merge_section(registry, "pages", extracted_pages)
            save_registry(output_dir, registry)
            yield sse_event("log", {"text": f"[Registry] Updated pages: {len(extracted_pages)} extracted"})

        # Full registry validation before QA
        reg_errors = validate_registry(registry)
        if reg_errors:
            report = format_validation_report(reg_errors)
            yield sse_event("log", {"text": f"[Registry] Pre-QA validation: {report}"})
            yield sse_event("registry_validation", {"phase": "pre_qa", "errors": [{"section": e.section, "name": e.name, "error": e.error, "suggestion": e.suggestion, "severity": e.severity} for e in reg_errors]})

            # Registry mismatches reported — QA agent will fix them

    # --- PAGE GATE: verify pages are complete and functional ---
    from services.phase_gates import check_page_completeness
    page_gate = check_page_completeness(output_dir, plan)
    if not page_gate["passed"]:
        yield sse_event("status", {"message": f"Fixing page issues ({issue_count} found)..."})
        try:
            async for evt in _stream_phase("Page-Fix", run_page_agent(output_dir, plan, domain_context=domain_ctx, design_spec=design_spec, fix_prompt=page_gate["retry_prompt"])):
                yield evt
            # Re-extract pages after fix
            extracted_pages = extract_pages_from_files(output_dir)
            if extracted_pages:
                registry = merge_section(registry, "pages", extracted_pages)
                save_registry(output_dir, registry)
        except Exception as e:
            yield sse_event("log", {"text": f"[Page Gate] Fix attempt failed: {e}"})
    else:
        yield sse_event("log", {"text": "[Page Gate] ✓ All pages complete and functional"})

    # COMPLETENESS (working-app): the monolithic page agent stalls on big apps, leaving
    # nav destinations with no schema -> blank routes. Fill each MISSING page with a
    # focused per-page LLM continuation (small call, internal retry), with a deterministic
    # minimal floor — so every route renders even if the page agent didn't finish.
    try:
        from services.page_completeness import fill_missing_pages
        _pgfill = await fill_missing_pages(output_dir, plan, domain_context=domain_ctx)
        if _pgfill["llm"] or _pgfill["minimal"]:
            yield sse_event("log", {"text": f"[Pages] completeness: {len(_pgfill['llm'])} via per-page continuation, {len(_pgfill['minimal'])} minimal floor"})
            extracted_pages = extract_pages_from_files(output_dir)
            if extracted_pages:
                registry = merge_section(registry, "pages", extracted_pages)
                save_registry(output_dir, registry)
    except Exception as _pce:
        yield sse_event("log", {"text": f"[Pages] completeness pass skipped: {_pce}"})

    # --- CROSS-REFERENCE GATE: verify pages call only existing API routes ---
    from services.phase_gates import check_cross_references
    xref_gate = check_cross_references(output_dir, plan)
    if not xref_gate["passed"]:
        xref_count = len(xref_gate["issues"])
        # Entity CRUD is served by the Data Engine catch-all (/api/data/[...path]), so
        # most "missing route" gaps are false positives. We no longer re-run a per-entity
        # API agent here — it would re-introduce the shadowing CRUD routes the prune pass
        # removed. Log only (non-fatal).
        yield sse_event("log", {"text": f"[X-Ref Gate] {xref_count} page→API reference(s) flagged (CRUD served by Data Engine catch-all; not regenerating per-entity routes)"})
    else:
        yield sse_event("log", {"text": "[X-Ref Gate] ✓ All page→API references resolve"})

    # --- UX TOLL GATE: verify domain-appropriate UX ---
    from services.phase_gates import check_ux_compliance
    ux_gate = check_ux_compliance(output_dir, plan, domain_label)
    if not ux_gate["passed"]:
        ux_issue_count = len(ux_gate["issues"])
        yield sse_event("log", {"text": f"[UX Gate] {ux_issue_count} domain UX issues — sending back to page agent"})
        yield sse_event("status", {"message": f"Applying {domain_label} UX patterns ({ux_issue_count} issues)..."})
        try:
            async for evt in _stream_phase("UX-Fix", run_page_agent(output_dir, plan, domain_context=domain_ctx, design_spec=design_spec, fix_prompt=ux_gate["retry_prompt"])):
                yield evt
        except Exception as e:
            yield sse_event("log", {"text": f"[UX Gate] Fix attempt failed: {e}"})
    else:
        yield sse_event("log", {"text": f"[UX Gate] ✓ {domain_label} UX compliance passed"})

    # --- Generate fallback workflow definitions (deterministic scaffolds) ---
    # The business logic agent should have generated complete definitions.
    # This fills any that are still empty as a safety net.
    if plan.get("workflows"):
        from services.workflow_generator import generate_workflow_definitions
        _det_wf = _deterministic_workflows()
        # IRF-M5-T4 wire: preview workflow-author intent before the stage runs.
        try:
            from services.stage_plan_emitter import preview as _sp_preview
            _sp_wf = _sp_preview("workflow_author")
            if _sp_wf.get("intent"):
                yield sse_event("stage_plan", _sp_wf)
        except Exception:  # noqa: BLE001
            pass
        if _det_wf:
            yield sse_event("status", {"message": "Generating domain workflows (deterministic)..."})
            _progress.phase_start("workflows")
            for _pe in _drain_progress():
                yield _pe
            _cf = chat_flavor.start("workflows")
            if _cf:
                yield sse_event("message", {"text": _cf})
        wf_count = generate_workflow_definitions(output_dir, plan)
        if wf_count:
            _label = "domain workflow(s) (deterministic)" if _det_wf else "workflow definition scaffolds (fallback)"
            yield sse_event("log", {"text": f"[Workflows] Built {wf_count} {_label}"})
        if _det_wf:
            _cf = chat_flavor.done("workflows", wf_count or len(plan.get("workflows") or []))
            if _cf:
                yield sse_event("message", {"text": _cf})
        # IRF-M5-T4 wire: record EditRecord on the ambient SessionContext.
        try:
            from services.stage_plan_emitter import record_after as _sp_record_after
            _sp_record_after("workflow_author", reason="pipeline run")
        except Exception:  # noqa: BLE001
            pass

    # Deterministic CRUD workflows — Create/Update/Delete<Entity> so action
    # buttons have a real workflow to dispatch (idempotent; won't clobber
    # domain workflows).
    try:
        from services.crud_workflow_generator import generate_crud_workflows
        _crud_plan = plan if (plan or {}).get("entities") else {"entities": (registry or {}).get("entities") or {}}
        _crud_written = generate_crud_workflows(_crud_plan, output_dir)
        if _crud_written:
            yield sse_event("log", {"text": f"[CRUD] generated {len(_crud_written)} workflow(s): {', '.join(_crud_written[:6])}"})
    except Exception as _crud_ex:
        yield sse_event("log", {"text": f"[CRUD] generation skipped: {_crud_ex}"})

    # Deliverable previews — workflows (domain workflows first, then CRUD rollup).
    try:
        from services.progress_events import iter_workflows as _iter_workflows
        for _rev in _iter_workflows(output_dir):
            yield sse_event("resource", _rev)
    except Exception:
        pass

    # --- WORKFLOW GATE: verify workflows are wired end-to-end ---
    if plan.get("workflows"):
        from services.phase_gates import check_workflow_integration
        wf_gate = check_workflow_integration(output_dir, plan)
        if not wf_gate["passed"]:
            wf_issue_count = len(wf_gate["issues"])
            if _deterministic_workflows():
                # Deterministic mode: the executability + graph gates below repair
                # these deterministically (or LLM-repair only prose steps) — no
                # 4-min BusinessLogic round-trip.
                yield sse_event("log", {"text": f"[Workflow Gate] {wf_issue_count} issue(s) — deferring to deterministic executability/graph gates"})
            else:
                yield sse_event("log", {"text": f"[Workflow Gate] {wf_issue_count} workflow issues — sending back to business logic agent"})
                yield sse_event("status", {"message": f"Completing workflow integration ({wf_issue_count} issues)..."})
                try:
                    async for evt in _stream_phase("Workflow-Fix", run_business_logic_agent(output_dir, plan, domain_context=domain_ctx)):
                        yield evt
                except Exception as e:
                    yield sse_event("log", {"text": f"[Workflow Gate] Fix attempt failed: {e}"})
        else:
            yield sse_event("log", {"text": "[Workflow Gate] ✓ Workflows fully integrated"})

    # COMPLETENESS (working-app): final workflow validity floor — repair any malformed
    # workflow file + create one for any plan workflow missing it, so the engine's
    # loadWorkflows() never crashes on a truncated/empty definition at runtime.
    try:
        from services.workflow_completeness import ensure_workflow_validity
        _wfres = ensure_workflow_validity(output_dir, plan)
        if _wfres["repaired"] or _wfres["created"]:
            yield sse_event("log", {"text": f"[Workflows] validity floor: repaired {len(_wfres['repaired'])}, created {len(_wfres['created'])}"})
    except Exception as _wfe:
        yield sse_event("log", {"text": f"[Workflows] validity floor skipped: {_wfe}"})

    # COMPLETENESS (working-app): executability contract — domain workflows whose
    # action nodes are PROSE (a 'description' string, no real params) are no-ops at
    # runtime. Regenerate them on the Anthropic SDK against the executability contract
    # so they actually do their db writes / emails / calls. CRUD workflows already
    # carry real db params and are left untouched.
    try:
        from services.workflow_executability import ensure_workflow_executability
        _wfx = await ensure_workflow_executability(output_dir, plan, domain_ctx)
        if _wfx["nonexecutable"]:
            yield sse_event("log", {"text": f"[Workflows] executability: regenerated {len(_wfx['repaired'])}/{len(_wfx['nonexecutable'])} prose workflow(s), {len(_wfx['still_nonexecutable'])} unresolved"})
    except Exception as _wfxe:
        yield sse_event("log", {"text": f"[Workflows] executability pass skipped: {_wfxe}"})

    # GRAPH GATE (deterministic): statically simulate each workflow — reachability,
    # dangling edges, missing terminal, dead-ends, invalid node/action types, missing
    # assignees — and auto-repair against the node contract so no workflow ships
    # structurally broken. Idempotent; unresolvable issues surface as warnings.
    try:
        from services.workflow_graph_gate import run_workflow_gate
        _gate = run_workflow_gate(output_dir, plan)
        if _gate["repaired"] or _gate["warnings"]:
            yield sse_event("log", {"text": f"[Workflows] graph gate: repaired {_gate['repaired']}/{_gate['checked']}, {_gate['warnings']} warning(s)"})
        # Variable provenance: a gateway/condition branching on a variable no
        # upstream node produces is a DEAD branch (every record takes the else
        # path). Flag it; under FORGE_BINDING_GATE=strict this is a build error,
        # else advisory. Never crashes the pipeline.
        _uv = _gate.get("unproduced_var_findings") or []
        if _uv:
            _strict = _binding_gate_is_strict(os.environ.get("FORGE_BINDING_GATE"))
            yield sse_event("log", {"text": f"[Workflows] {len(_uv)} dead gateway branch(es) — variable never produced upstream ({'strict' if _strict else 'warn'} mode):"})
            for _f in _uv[:25]:
                yield sse_event("log", {"text": f"[Workflows] ⚠ {_f.get('workflow')} {_f.get('node')}: '{_f.get('variable')}' unproduced ({_f.get('expression')})"})
            if _strict:
                yield sse_event("status", {"message": f"Generation failed: {len(_uv)} workflow gateway(s) branch on a variable no upstream node produces (dead branch). Set FORGE_BINDING_GATE=warn to bypass."})
                yield sse_event("error", {"message": f"workflow_variable_gate: {len(_uv)} unproduced gateway variable(s)", "errors": _uv[:25]})
    except Exception as _gate_e:
        yield sse_event("log", {"text": f"[Workflows] graph gate skipped: {_gate_e}"})

    # Seed is NOT executed at generation time.
    #
    # The runtime injector always copies the authoritative seed.ts template
    # into the app, and the generated app's start.sh runs it on every boot
    # (with the fingerprint-based skip guard in seed.ts making the rerun
    # cheap when the schema shape + row data are unchanged). Running
    # `npx tsx src/db/seed.ts` here would need a live Postgres this
    # process can't reach anyway. Data authoring (row synthesis into
    # seed-plan.json) still runs in post_generate_fixes because it's a
    # deterministic file-writing pass, not seed execution.

    # === Phase: fidelity_loop (Phase 14) ===
    if FIDELITY_LOOP_ENABLED:
        yield sse_event("phase_start", {"phase": "fidelity_loop"})
        try:
            # Build page list from the plan's pages array (registry pages is a
            # dict keyed by route; plan.pages gives us route + description).
            plan_pages = plan.get("pages", [])
            page_refs: list[PageRef] = []
            for p in plan_pages:
                route = p.get("route", "") if isinstance(p, dict) else getattr(p, "route", "")
                page_path = route.lstrip("/") or p.get("name", "")
                role = p.get("role", "") if isinstance(p, dict) else getattr(p, "role", "")

                class _Brief:
                    pass
                brief = _Brief()
                brief.route = route
                brief.role = role

                page_type = infer_page_type(brief)
                page_refs.append(PageRef(
                    short_id=project_short_id,
                    page_path=page_path,
                    page_route=route,
                    page_type=page_type,
                ))

            runner = FidelityLoopRunner(
                output_dir=output_dir,
                project_ctx=ProjectContext(
                    domain=domain_label or "general",
                    app_name=plan.get("appName", "App"),
                    description=description or plan.get("description", ""),
                    tone=plan.get("tone", "professional"),
                ),
                sse_emit=lambda et, d: sse_event(et, d),
            )
            report = await runner.run(page_refs)
            yield sse_event("phase_complete", report.summary())
        except Exception as e:
            # Fidelity loop failure must NEVER block generation.
            logger.exception("fidelity_loop failed; continuing pipeline")
            yield sse_event("phase_warning", {"phase": "fidelity_loop", "error": str(e)})
    # === end fidelity_loop ===

    # Handoff: seed → QA
    yield sse_event("office", agent_handoff_event("seed_generator", "qa_tester", artifact="seed_data"))

    # Phase 6.5: Completeness validation — find gaps before QA
    from services.completeness_validator import validate_completeness, format_issues_for_agent
    completeness_issues = validate_completeness(output_dir)
    completeness_report = format_issues_for_agent(completeness_issues)
    if completeness_issues:
        critical_count = sum(1 for i in completeness_issues if i["severity"] == "critical")
        yield sse_event("log", {"text": f"[Completeness] Found {critical_count} critical issues, {len(completeness_issues) - critical_count} warnings"})
    else:
        yield sse_event("log", {"text": "[Completeness] All checks passed"})

    _progress.phase_start("qa")
    for _pe in _drain_progress():
        yield _pe
    # Phase 7: QA verification — includes completeness issues
    yield sse_event("status", {"message": "Running QA verification..."})
    for aid in PHASE_TO_AGENTS["qa"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["qa"]))
    async for evt in _stream_phase("QA", run_qa_agent(output_dir, plan, domain_context=domain_ctx, extra_context=completeness_report)):
        yield evt
    for aid in PHASE_TO_AGENTS["qa"]:
        yield sse_event("office", agent_complete_event(aid))

    # Clear stale build cache
    apply_post_generate_fixes(output_dir)

    # ── CODER → REVIEWER → CODER CYCLE ──
    # Profile-driven: Fast caps the build-fix loop (2), Complete is thorough (5).
    # Each cycle can run a real npm build + LLM fix (minutes), so this is one of
    # the biggest fast-vs-deep levers. Exits early the moment the build is clean.
    _gp = _gen_profile(output_dir)
    MAX_REVIEW_CYCLES = _gp.review_cycles if _gp else 5
    build_ok = False  # authoritative: set only by a real `npm run build` exit 0

    for cycle in range(MAX_REVIEW_CYCLES):
        cycle_label = f"cycle {cycle + 1}/{MAX_REVIEW_CYCLES}"
        yield sse_event("status", {"message": f"Build review ({cycle_label})..."})
        yield sse_event("office", agent_handoff_event("qa_tester", "validator", artifact="code"))

        # REVIEWER: validator scans and reports bugs
        for aid in PHASE_TO_AGENTS["validation"]:
            yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["validation"]))

        collected_validator_text: list[str] = []
        async for evt in _stream_phase("Validator", run_validator(output_dir, domain=domain_label, description=description)):
            event_type = evt.get("event")
            if event_type in ("log", "message"):
                data = json.loads(evt["data"]) if isinstance(evt.get("data"), str) else evt.get("data", {})
                text = data.get("text", "")
                if text:
                    collected_validator_text.append(text)
            yield evt

        for aid in PHASE_TO_AGENTS["validation"]:
            yield sse_event("office", agent_complete_event(aid))

        # Check if build passed
        validator_output = "\n".join(collected_validator_text)
        build_passed = any(kw in validator_output.lower() for kw in [
            "build: pass", '"pass"', "zero errors", "compiled successfully", "build passed",
        ])
        has_errors = any(kw in validator_output.lower() for kw in [
            "syntax error", "module not found", "unexpected token", "failed to compile",
        ])

        # Authoritative build gate: the keyword scan above is only a HINT — the
        # real `npm run build` exit code decides. We never break "clean" on a
        # false keyword-pass, and a persistent failure is surfaced loudly instead
        # of silently shipping. The (slow) real build runs only when the heuristic
        # thinks we're done OR on the final cycle — usually 1–2 builds, not 5.
        if (build_passed and not has_errors) or cycle == MAX_REVIEW_CYCLES - 1:
            yield sse_event("status", {"message": f"Verifying real build ({cycle_label})..."})
            _ok, _errs = await _real_build_ok(output_dir)
            if _ok:
                build_ok = True
                yield sse_event("log", {"text": f"[Build] ✓ Real npm build passed on {cycle_label}"})
                break
            if cycle == MAX_REVIEW_CYCLES - 1:
                build_ok = False
                yield sse_event("log", {"text": f"[Build] ✗ Build STILL FAILING after {MAX_REVIEW_CYCLES} cycles — real errors:\n{(_errs or '(no parseable errors)')[:1500]}"})
                break
            # Heuristic said pass but the real build failed — override with the
            # ground-truth errors and keep iterating.
            yield sse_event("log", {"text": "[Build] Heuristic pass but real build FAILED — feeding real errors to the coder"})
            validator_output = _errs or validator_output

        # CODER: send bugs back to page agent to fix
        yield sse_event("log", {"text": f"[Build] Errors found — sending back to coder"})
        yield sse_event("status", {"message": f"Fixing build errors ({cycle_label})..."})

        fix_prompt = (
            f"The build reviewer found errors. Fix ALL of them:\n\n"
            f"{validator_output[-3000:]}\n\n"
            f"Read each file, fix the error, verify with `npx tsc --noEmit 2>&1 | head -30`."
        )
        try:
            async for evt in _stream_phase(
                "Build-Fix",
                run_page_agent(output_dir, plan, domain_context=domain_ctx, design_spec=design_spec, fix_prompt=fix_prompt),
            ):
                yield evt
        except Exception as e:
            yield sse_event("log", {"text": f"[Build] Fix failed: {e}"})

    # ── VISUAL REVIEW PHASE ──
    yield sse_event("status", {"message": "Visual design review..."})
    try:
        from screenshot import capture_page_screenshot, capture_key_pages
        from agent import run_design_reviewer_agent, run_fixer_agent
        from services.preview_manager import start_project_environment, stop_project_environment

        short_id = Path(output_dir).name
        env_info = await start_project_environment(short_id, output_dir, with_database=False)
        preview_port = env_info.get("port")

        if preview_port:
            MAX_VISUAL_CYCLES = 3
            for vis_cycle in range(MAX_VISUAL_CYCLES):
                yield sse_event("log", {"text": f"[Visual] Review cycle {vis_cycle + 1}/{MAX_VISUAL_CYCLES}"})

                screenshots = await capture_key_pages(output_dir, preview_port)
                if not screenshots:
                    yield sse_event("log", {"text": "[Visual] No screenshots captured — skipping"})
                    break

                all_approved = True
                all_issues: list[str] = []
                for page_info in screenshots:
                    review = await run_design_reviewer_agent(
                        output_dir, page_info["route"], page_info["screenshot"],
                        domain=domain_label, description=description,
                    )
                    if "APPROVED" in review.upper():
                        yield sse_event("log", {"text": f"[Visual] ✓ {page_info['route']} approved"})
                    else:
                        all_approved = False
                        all_issues.append(f"## {page_info['route']}\n{review}")
                        yield sse_event("log", {"text": f"[Visual] ✗ {page_info['route']} — issues found"})

                if all_approved:
                    yield sse_event("log", {"text": f"[Visual] ✓ Design approved on cycle {vis_cycle + 1}"})
                    break

                if vis_cycle == MAX_VISUAL_CYCLES - 1:
                    break

                # Send to fixer
                yield sse_event("status", {"message": f"Fixing visual issues ({vis_cycle + 1})..."})
                async for evt in stream_agent_messages(
                    run_fixer_agent(output_dir, "\n\n".join(all_issues)),
                    output_dir=output_dir, event_prefix="[Visual-Fix] ",
                ):
                    if evt.get("event") == "agent_result":
                        data = json.loads(evt["data"])
                        total_cost += data.get("cost_usd", 0)
                        total_turns += data.get("num_turns", 0)
                    else:
                        yield evt

            try:
                await stop_project_environment(short_id)
            except Exception:
                pass
        else:
            yield sse_event("log", {"text": "[Visual] Could not start preview — skipping"})
    except Exception as e:
        yield sse_event("log", {"text": f"[Visual] Review skipped: {e}"})

    # ── FLOW SNAPSHOT VALIDATION (deterministic — no LLM) ──
    yield sse_event("status", {"message": "Validating navigation flow..."})
    try:
        from services.flow_validator import validate_navigation_flow
        flow_result = validate_navigation_flow(output_dir)
        stats = flow_result.get("stats", {})
        yield sse_event("log", {
            "text": f"[Flow] Checked {stats.get('checked', 0)} interactions — "
                    f"{stats.get('passed', 0)} passed, {stats.get('failed', 0)} failed"
        })
        if not flow_result["passed"] and flow_result.get("fix_prompt"):
            yield sse_event("status", {"message": f"Fixing {stats.get('failed', 0)} flow issues..."})
            try:
                async for evt in _stream_phase("Flow-Fix", run_page_agent(
                    output_dir, plan, domain_context=domain_ctx,
                    design_spec=design_spec, fix_prompt=flow_result["fix_prompt"])):
                    yield evt
            except Exception as e:
                yield sse_event("log", {"text": f"[Flow] Fix failed: {e}"})
        elif flow_result["passed"]:
            yield sse_event("log", {"text": "[Flow] ✓ All navigation interactions verified"})
    except Exception as e:
        yield sse_event("log", {"text": f"[Flow] Validation skipped: {e}"})

    # ── BROWSER VALIDATION (automated Playwright trace) ──
    yield sse_event("status", {"message": "Browser validation..."})
    try:
        from services.browser_validator import run_browser_validation
        from services.preview_manager import start_project_environment, stop_project_environment

        project_short_id = Path(output_dir).name
        env_result = await start_project_environment(project_short_id, output_dir, with_database=False)
        preview_port = env_result.get("port")

        if preview_port:
            yield sse_event("log", {"text": f"[Browser] Dev server on port {preview_port}"})
            browser_result = await run_browser_validation(output_dir, preview_port)
            yield sse_event("log", {"text": f"[Browser] {browser_result['summary']}"})

            if not browser_result["passed"] and browser_result.get("fix_prompt"):
                yield sse_event("status", {"message": "Fixing runtime issues..."})
                try:
                    async for evt in _stream_phase("Browser-Fix", run_page_agent(
                        output_dir, plan, domain_context=domain_ctx,
                        design_spec=design_spec, fix_prompt=browser_result["fix_prompt"])):
                        yield evt

                    # Re-validate after fix
                    browser_result2 = await run_browser_validation(output_dir, preview_port)
                    yield sse_event("log", {"text": f"[Browser] Re-validation: {browser_result2['summary']}"})
                except Exception as e:
                    yield sse_event("log", {"text": f"[Browser] Fix failed: {e}"})
            elif browser_result["passed"]:
                yield sse_event("log", {"text": "[Browser] ✓ All pages load cleanly"})

            await stop_project_environment(project_short_id)
        else:
            yield sse_event("log", {"text": "[Browser] Could not start dev server — skipping"})
    except Exception as e:
        yield sse_event("log", {"text": f"[Browser] Validation skipped: {e}"})

    # Handoff: → indexer
    yield sse_event("office", agent_handoff_event("validator", "indexer", artifact="build_output"))

    # Phase 9: Indexing
    yield sse_event("status", {"message": "Indexing application..."})
    for aid in PHASE_TO_AGENTS["indexing"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["indexing"]))
    async for evt in _stream_phase("Indexer", run_indexer(output_dir)):
        yield evt
    for aid in PHASE_TO_AGENTS["indexing"]:
        yield sse_event("office", agent_complete_event(aid))

    # ── FINAL VERIFY (additional automated checks) ──
    try:
        from services.verify_pipeline import run_verify_pipeline
        verify = await run_verify_pipeline(output_dir, plan=plan)
        if verify.get("css") and not verify["css"]["passed"]:
            for issue in verify["css"]["issues"]:
                yield sse_event("log", {"text": f"[Verify] CSS: {issue}"})
        if verify.get("pages") and not verify["pages"]["passed"]:
            for issue in verify["pages"]["issues"][:5]:
                yield sse_event("log", {"text": f"[Verify] Page: {issue}"})
    except Exception as e:
        yield sse_event("log", {"text": f"[Verify] Skipped: {e}"})

    # ── JOURNEY GATE (post-generation end-to-end verification) ──
    # Runs the app's declared user journeys with Playwright against the running
    # dev server. Off by default; set FORGE_JOURNEY_GATE=warn to log outcomes,
    # or =strict to block generation on failure. Gate silently skips if the
    # app isn't reachable (dev server not up in this environment).
    try:
        from services.journey_gate import run_journey_gate, JourneyGateFailure
        _journey_url = os.environ.get("FORGE_JOURNEY_BASE_URL", "http://localhost:3000")
        async for _jevt in run_journey_gate(output_dir, base_url=_journey_url):
            yield _jevt
    except JourneyGateFailure as _jgf:
        # Strict mode + failure → surface a loud terminal error that the
        # frontend can distinguish from an infra issue. Hints ride along
        # so downstream tooling (SV harness, Smith) can pick up a
        # structured remediation payload without re-parsing the summary.
        yield sse_event("error", {
            "error": f"journey_gate: {_jgf.summary}",
            "journeys": _jgf.journeys,
            "hints": _jgf.hints,
        })
        raise
    except Exception as e:
        yield sse_event("log", {"text": f"[Journey] Skipped: {e}"})

    # ── FIDELITY SCORING (advisory, opt-in via env) ──
    try:
        async for evt in _stream_fidelity_scoring(output_dir, plan):
            yield evt
    except Exception as e:
        yield sse_event("log", {"text": f"[Fidelity] Pipeline skipped: {e}"})

    # ── SEED-SMOKE GATE (opt-in via FORGE_SEED_SMOKE; needs Docker) ──
    # Run the app's own `start.sh --seed-only` (boot Postgres + migrate + seed,
    # then stop) so ANY schema/seed mismatch (users.password, uuid PK/FK classes)
    # is caught HERE at build time instead of on the user's first click. Off by
    # default (adds ~1-2 min, needs Docker); never crashes the pipeline.
    try:
        from services.seed_smoke import (
            is_enabled as _seed_enabled,
            run_seed_smoke_async as _run_seed_smoke,
            summarize as _seed_summary,
        )
        if _seed_enabled():
            yield sse_event("log", {"text": "[SeedSmoke] Booting Postgres + migrate + seed (FORGE_SEED_SMOKE on)..."})
            _seed_res = await _run_seed_smoke(output_dir)
            yield sse_event("log", {"text": f"[SeedSmoke] {_seed_summary(_seed_res)}"})
            if not _seed_res.get("skipped") and not _seed_res.get("ok"):
                for _err in (_seed_res.get("errors") or [])[:5]:
                    yield sse_event("log", {"text": f"[SeedSmoke] ⚠ {_err}"})
    except Exception as _seed_ex:  # noqa: BLE001 — the gate must never fail the build
        yield sse_event("log", {"text": f"[SeedSmoke] skipped: {_seed_ex}"})

    # ── BINDING GATE (Slice 1) — every UI ref must resolve to a real resource ──
    async for evt in _stream_binding_gate(output_dir):
        yield evt

    # ── AUTO-INSTALL APP AGENT from plan.agent_graph (SP4.5) ──────────
    # Runs AFTER schema/entities/workflows have landed so the code_editor
    # has full app context when writing agent-service.ts. Non-fatal: a
    # failure here (missing MCP server, code_editor timeout, etc.) must
    # NOT fail the whole app generation — the user can retry via the
    # Agent Builder UI. See services/agent_from_plan.py.
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
                        output_dir=output_dir,
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
    except Exception:
        logger.exception("[pipeline] agent auto-install failed (non-fatal)")
        yield sse_event("log", {"text": "[Agent] auto-install skipped (see server log)"})

    # Build success
    _write_timing()
    yield sse_event("log", {"text": f"[Timing] total: {sum(_phase_timings.values()):.1f}s — generation-timing.json written"})
    yield sse_event("office", build_success_event())

    # Yield combined totals
    yield sse_event("agent_result", {
        "num_turns": total_turns,
        "cost_usd": total_cost,
        "duration_ms": total_duration,
    })
    logger.info(
        "[pipeline] COMPLETE relay pipeline output_dir=%s elapsed=%.1fs last_phase=%s",
        output_dir, time.perf_counter() - _pipeline_t0, _pipeline_last_phase["name"],
    )


def _build_design_source(source, *, output_dir: str | None = None, project_id=None):
    """The DesignSource adapter for a PlanSource, or None for text."""
    try:
        if source.is_figma:
            from services.design_source.figma import FigmaSource
            return FigmaSource(
                source.design_ref, source.secret,
                output_dir=output_dir, project_id=str(project_id) if project_id else None,
            )
        if source.is_uxpilot:
            from services.design_source.uxpilot import UxPilotSource
            return UxPilotSource.from_credentials(source.design_ref, source.secret or "")
    except Exception as exc:  # noqa: BLE001 — the pipeline logs and continues without import
        logger.warning("[design] adapter for %s could not be built: %s", source.kind, exc)
    return None


async def _run_figma_relay_pipeline(
    output_dir: str,
    plan: dict,
    description: str,
    figma_url: str,
    figma_token: str,
    domain_context: dict | None = None,
    project_id: uuid.UUID | None = None,
) -> AsyncIterator[dict]:
    """Figma-era entry: the design pipeline with a Figma PlanSource."""
    from services.pipeline.source import PlanSource
    async for evt in _run_design_relay_pipeline(
        output_dir=output_dir,
        plan=plan,
        description=description,
        source=PlanSource.figma(url=figma_url, token=figma_token),
        domain_context=domain_context,
        project_id=project_id,
    ):
        yield evt


async def _run_design_relay_pipeline(
    output_dir: str,
    plan: dict,
    description: str,
    source,
    domain_context: dict | None = None,
    project_id: uuid.UUID | None = None,
) -> AsyncIterator[dict]:
    """Run the relay pipeline for a project built from an imported design.

    Same as _run_relay_pipeline() for phases 1-3 and 6-9. Before them, the
    design's pages are imported as PageV2 schemas through the provider's
    :class:`services.design_source.DesignSource` (the shared
    ``phase_design_import``); the Figma REST mapper and refiner run first
    for a Figma source only, because they read Figma's node tree.

    ``source`` is the :class:`PlanSource` (kind figma or uxpilot).
    `domain_context`: same semantics as _run_relay_pipeline. When supplied,
    skip the inline discovery call in Layer 1.
    """
    # The Figma-era locals: every Figma-only block below reads them. They
    # resolve to "" for any other provider, and those blocks are guarded on
    # ``source.is_figma`` so an empty URL never reaches the Figma clients.
    figma_url: str = source.figma_url or ""
    figma_token: str = source.figma_token or ""
    _design = _build_design_source(source, output_dir=output_dir, project_id=project_id)

    from agents.contract_agent import run_contract_agent
    from agents.schema_agent import run_schema_agent
    from agents.auth_agent import run_auth_agent
    from agents.api_agent import run_api_agent
    from agents.business_logic_agent import run_business_logic_agent
    from agents.figma_ui_agent import run_figma_ui_agent
    from agents.qa_agent import run_qa_agent
    from agents.validator import run_validator
    from agents.indexer import run_indexer
    from services.parallel_runner import run_parallel_agents, stream_with_idle_timeout
    from agents.domain_agent import run_domain_discovery, persist_discovery
    # `shutil` is used at several sites in this function (asset copy at
    # ~4107, template-tree copy later). A local `import shutil` inside a
    # single branch makes Python treat `shutil` as a local variable for
    # the WHOLE function scope, so any earlier reference raises
    # UnboundLocalError. Hoist the import here so every branch sees it.
    import shutil  # noqa: F401 — used at multiple sites below

    # Single normalization choke point (see _run_relay_pipeline). Figma-driven
    # plans can also arrive raw (entities as a DICT) — normalize before any
    # consumer (discovery, registry, schema) reads the entity list.
    plan = _ensure_normalized_plan(plan)

    # IRF-M5-T2 (lite): stamp the ambient SessionContext for this figma
    # run, mirroring the text-based pipeline. Silent guard preserves
    # historic behavior on any plumbing failure.
    try:
        from services.session_context import from_plan as _sc_from_plan
        from services.session_context import set_current as _sc_set_current
        _sc_set_current(_sc_from_plan(plan))
    except Exception:  # noqa: BLE001
        pass

    # Stamp app-level archetype — mirrors _run_relay_pipeline so downstream
    # (archetype_workflows.find_emitter, runtime_injector EXTERNALS, etc.)
    # sees the same signal from both entry points. Keyword classifier only,
    # no LLM. See _run_relay_pipeline for full rationale.
    try:
        if isinstance(plan, dict) and not (plan.get("archetype") or plan.get("app_archetype")):
            from services.app_design_catalog import classify_app_archetype as _classify_arche
            _brief_text = (
                plan.get("description") or plan.get("brief") or plan.get("prompt") or ""
            )
            _matched_archetype = _classify_arche(_brief_text)
            if _matched_archetype:
                plan["archetype"] = _matched_archetype
                logger.info("[plan/figma] stamped archetype=%s from classifier", _matched_archetype)
    except Exception as _arche_exc:  # noqa: BLE001
        logger.warning("[plan/figma] archetype stamp skipped: %s", _arche_exc)

    # Mirror of the text pipeline's required-page injection. See rationale
    # above _ensure_required_pages in _run_relay_pipeline.
    try:
        from services.archetypes import (
            ensure_required_pages as _ensure_pages,
            ensure_required_workflows as _ensure_wfs,
            ensure_required_columns as _ensure_cols,
        )
        _n = _ensure_pages(plan)
        if _n:
            logger.info("[plan/figma] injected %d required page(s) for archetype=%s",
                        _n, plan.get("archetype"))
        _nw = _ensure_wfs(plan)
        _nc = _ensure_cols(plan)
        if _nw or _nc:
            logger.info("[plan/figma] injected %d required workflow(s), %d column(s) "
                        "for archetype=%s", _nw, _nc, plan.get("archetype"))
    except Exception as _req_exc:  # noqa: BLE001
        logger.warning("[plan/figma] required-pages injection skipped: %s", _req_exc)

    # Progress tracker — hoisted to the top of the function so every branch
    # (including the discovery-else path below) can safely call
    # `_progress.phase_start(...)`. Same UnboundLocalError root cause as
    # `_run_relay_pipeline` — kept identical here so the Figma pipeline can't
    # regress the fix. B-022.2 (both LLM + Figma paths were exposed).
    from services.progress import ProgressTracker as _ProgressTracker
    _pending_progress: list[dict] = []
    _progress = _ProgressTracker(
        emit_fn=lambda k, d: _pending_progress.append(sse_event(k, d)),
    )
    def _drain_progress():
        while _pending_progress:
            yield _pending_progress.pop(0)

    # ── Layer 1 — Foundation: domain discovery (Figma pipeline) ───────────
    # Same domain agent + same user-approval kwarg semantics as the LLM
    # pipeline. The Figma file supplies visual ground truth, but persona /
    # compliance / common pitfalls are still useful for the downstream
    # contract / api / business-logic agents.
    # Load the design context from disk (written at import time by
    # services.design_import / extract_figma_context). Present here means
    # brief_from_figma will run — palette/typography/radius measured from the
    # design, no LLM in the design decision chain. Absent means brief_author
    # fallback. The aggregator is provider-agnostic; only its name is Figma's.
    def _load_figma_ctx() -> dict | None:
        try:
            from services.design_context import read_design_context
            return read_design_context(output_dir)
        except Exception:  # noqa: BLE001
            return None

    _figma_ctx_for_brief = _load_figma_ctx()

    if domain_context is not None:
        domain_ctx = domain_context
        persist_discovery(output_dir, domain_ctx)
        await _author_and_persist_brief(output_dir, domain_ctx, plan,
                                        figma_context=_figma_ctx_for_brief,
                                        project_id=str(project_id) if project_id else None)
        yield sse_event("log", {
            "text": f"[Discovery] ✓ Using user-approved domain context: {domain_ctx.get('domain', 'Generic')}"
        })
    else:
        yield sse_event("status", {"message": "Researching domain context..."})
        _progress.phase_start("discovery")
        for _pe in _drain_progress():
            yield _pe
        yield sse_event("log", {"text": "[Discovery] Researching domain (web search enabled)..."})
        try:
            domain_ctx = await run_domain_discovery(description, plan, enable_web_search=True)
        except Exception as _disc_exc:
            yield sse_event("log", {
                "text": f"[Discovery] ⚠ FAILED: {_disc_exc} — aborting generation"
            })
            raise
        persist_discovery(output_dir, domain_ctx)
        await _author_and_persist_brief(output_dir, domain_ctx, plan,
                                        figma_context=_figma_ctx_for_brief,
                                        project_id=str(project_id) if project_id else None)
        yield sse_event("log", {
            "text": f"[Discovery] ✓ Domain: {domain_ctx.get('domain', 'Generic')}"
        })
    # Used by run_validator + UX compliance gate further down. Must be set in
    # both branches above — referenced unconditionally later.
    domain_label = domain_ctx.get("domain", "Generic")

    # Reachability guard (SP3.2): promote any entity left orphaned (no page + no relation)
    # before the registry is built so the promoted page flows through page generation.
    try:
        from services.app_design_guardrail import ensure_entity_reachability
        plan, _reach = ensure_entity_reachability(plan)
        if _reach["promoted"]:
            yield sse_event("log", {"text": f"[Design] promoted orphaned entities to pages: {_reach['promoted']}"})
    except Exception as _r_ex:
        yield sse_event("log", {"text": f"[Design] reachability guard skipped: {_r_ex}"})

    # ── Parity with text pipeline: domain reclass → plan persist → maquette ──
    # The text pipeline (_run_relay_pipeline) runs these steps before any
    # downstream authoring reads plan.json. The Figma pipeline shares every
    # downstream reader (canonical registry, schema/api/biz agents, post-generate
    # fixes) so it must run the same steps or Figma runs silently lose richer
    # domain classification and the dashboard maquette.
    try:
        from services.plan_finalize import reclassify_plan_domain as _reclass_domain_f
        _before_f, _after_f, _changed_f = _reclass_domain_f(plan)
        if _changed_f:
            yield sse_event("log", {"text": (
                f"[figma/domain] reclassified {_before_f!r} → {_after_f!r}"
            )})
    except Exception as _dom_f_exc:  # noqa: BLE001
        logger.warning("[figma/domain] reclassify skipped: %s", _dom_f_exc)

    # Directive parser — same enrichment as the text pipeline (Preset,
    # Row-click, Gauges → plan.hints; archetype backfill from vocab).
    try:
        from services.plan_directive_parser import enrich_plan_with_directives as _enrich_f
        _added_f = _enrich_f(plan)
        if _added_f:
            logger.info("[figma/plan] directive-parser found: %s", ", ".join(_added_f))
    except Exception as _dir_f_exc:  # noqa: BLE001
        logger.warning("[figma/plan] directive parser skipped: %s", _dir_f_exc)

    # Persist requirement.json (Slice 2 — same as text pipeline).
    try:
        from services.requirement import ensure_requirement as _ensure_req_f
        _prompt_f = plan.get("description") or plan.get("brief") or plan.get("prompt") or ""
        _ensure_req_f(output_dir, _prompt_f)
    except Exception as _req_f_exc:  # noqa: BLE001
        logger.warning("[figma/requirement] persist skipped: %s", _req_f_exc)

    # Persist the canonical plan.json (same seam as text pipeline).
    try:
        from services.plan_canonicalizer import canonicalize_plan as _canon_f
        plan, _canon_report_f = _canon_f(plan)
        _canon_changes_f = {k: v for k, v in
                            _canon_report_f["summary"].items() if v}
        if _canon_changes_f:
            logger.info("[figma/plan-canonicalize] normalized: %s",
                        _canon_changes_f)
        _contracts_dir_f = Path(output_dir) / "src" / "contracts"
        _contracts_dir_f.mkdir(parents=True, exist_ok=True)
        (_contracts_dir_f / "plan.json").write_text(
            json.dumps(plan, indent=2, default=str), encoding="utf-8"
        )
    except Exception as _plan_f_exc:  # noqa: BLE001
        logger.warning("[figma/plan-persist] skipped: %s", _plan_f_exc)

    try:
        from services.plan_finalize import (
            author_dashboard_maquette_if_enabled as _author_maq_if_enabled,
            author_collection_maquettes_if_enabled as _author_col_maq_if_enabled,
            author_record_maquettes_if_enabled as _author_rec_maq_if_enabled,
            ensure_composition_reference as _ensure_comp_ref,
        )
        # Montage first — the three authors below read what it writes.
        _comp_ref = await _ensure_comp_ref(
            plan, output_dir, str(project_id) if project_id else None)
        if _comp_ref is not None:
            yield sse_event("log", {"text": (
                "[figma/montage] composition reference: "
                + (", ".join(sorted(_comp_ref.get("screens") or {}))
                   or "layout only"))})
        _maq_f = await _author_maq_if_enabled(plan, output_dir)
        if _maq_f is not None:
            yield sse_event("log", {"text": (
                f"[figma/maquette] authored {len(_maq_f.get('kpis') or [])} KPIs, "
                f"chart={'y' if _maq_f.get('primary_chart') else 'n'}"
            )})
        _col_maq_f = await _author_col_maq_if_enabled(plan, output_dir)
        if _col_maq_f is not None:
            yield sse_event("log", {"text": (
                f"[figma/maquette/collection] wrote {len(_col_maq_f)} collection maquette(s)"
            )})
        _rec_maq_f = await _author_rec_maq_if_enabled(plan, output_dir)
        if _rec_maq_f is not None:
            yield sse_event("log", {"text": (
                f"[figma/maquette/record] wrote {len(_rec_maq_f)} record maquette(s)"
            )})
    except Exception as _maq_f_exc:  # noqa: BLE001
        logger.warning("[figma/maquette] skipped: %s", _maq_f_exc)

    # Canonical Resource Registry — the single naming authority, built once from the
    # finalized plan. ADDITIVE for now (persisted, not yet consumed); later phases flip
    # each generator to read it instead of re-deriving names.
    try:
        from services.resource_registry import build_canonical_registry, write_registry
        _canon_reg = build_canonical_registry(plan)
        write_registry(_canon_reg, output_dir)
        logger.info("resource-registry.json written: %d entities", len(_canon_reg.get("entities", {})))
    except Exception as e:  # noqa: BLE001 — never block generation
        logger.warning("build_canonical_registry skipped: %s", e)

    # FK-semantics authority — classify every FK column's role (actor/domain/
    # tenancy/plain) from the registry's real FK targets. Emitted right after the
    # canonical registry so backend consumers read roles, never guess by name.
    try:
        from services.fk_semantics import emit_fk_semantics
        emit_fk_semantics(output_dir)
    except Exception as e:  # noqa: BLE001 — never block generation
        logger.warning("emit_fk_semantics skipped: %s", e)

    # Initialize contract registry from plan
    registry = create_registry(plan)
    save_registry(output_dir, registry)
    _removed = _clean_schemas_dir(output_dir)
    if _removed > 0:
        yield sse_event("log", {"text": f"[Cleanup] Removed {_removed} stale schema file(s) from src/schemas/"})

    # Surface design-driven plan information so the user sees what scope was inferred.
    if (plan or {}).get("_design_driven") or (plan or {}).get("_figma_driven"):
        _routes = [p.get("route") for p in (plan.get("pages") or [])]
        _prov = ((plan.get("design") or {}).get("provider") or source.provider or "design")
        yield sse_event("log", {
            "text": f"[Design Plan] Driven by {_prov} — {len(_routes)} page(s): {_routes}"
        })

    # Track which routes the deterministic mapper successfully emits. Used
    # later by run_schema_frontend_pipeline's skip_routes filter so the LLM
    # schema pipeline doesn't overwrite Figma-emitted pages.
    deterministic_pages: set[str] = set()

    # The Figma REST node-tree mapper, its SVG export and its theme-token
    # merge live in services.design_source.figma now (the ``schema`` markup
    # kind); the shared import phase below runs them for a Figma source
    # whenever Dev Mode JSX is not available.

    # ── DESIGN IMPORT (every provider) ──
    # One page schema per design ref through the provider's DesignSource:
    # Figma Dev Mode JSX or UX Pilot HTML, the same element mapping behind
    # both. Replaces the Figma-only MCP block. Routes it writes join
    # ``deterministic_pages`` so the schema authoring phase skips them.
    if _design is not None:
        from services.pipeline.phase_design_import import phase_design_import as _phase_design_import
        async for _evt in _phase_design_import(
            None, plan,
            source=_design,
            output_dir=output_dir,
            project_id=project_id,
            imported_routes=deterministic_pages,
        ):
            yield _evt
    else:
        yield sse_event("log", {"text": f"[DesignImport] no adapter for provider {source.provider!r} — skipping import"})
    # ── END DESIGN IMPORT ──

    # ── BINDING PASS (plan-driven) ───────────────────────────────────────────
    # Body lifted to services.pipeline.phase_figma_pre.phase_figma_binding_pass
    # in Phase 1e.
    from services.pipeline.phase_figma_pre import phase_figma_binding_pass as _phase_figma_binding_pass
    async for _evt in _phase_figma_binding_pass(
        None,
        plan,
        output_dir=output_dir,
        registry=registry,
    ):
        yield _evt

    total_cost = 0.0
    total_turns = 0
    total_duration = 0

    # Per-phase wall-clock timing (seconds). Written to generation-timing.json
    # at the end of the pipeline. Bookkeeping is best-effort — never fatal.
    _phase_timings: dict[str, float] = {}

    # Progress tracker was hoisted to the top of this pipeline so the
    # discovery-else branch above couldn't crash with UnboundLocalError
    # (B-022.2). Init here is intentionally removed — the earlier one is
    # authoritative. The phase→key map still lives here so it stays adjacent
    # to the phase-emitting call sites below.
    _STREAM_PHASE_TO_KEY = {
        "Design":        "design",
        "Contract":      "contract",
        "Contract-Fix":  "contract",
        "Schema":        "schema",
        "BusinessLogic": "bizlogic_api",
        "API":           "bizlogic_api",
        "Component":     "components",
        "Component-Fix": "components",
        "Page":          "pages",
        "Page-Fix":      "pages",
        "UX-Fix":        "pages",
        "Workflow":      "workflows",
        "Workflow-Fix":  "workflows",
        "Auth-Fix":      "auth",
    }

    def _write_timing():
        try:
            total = sum(_phase_timings.values())
            (Path(output_dir) / "generation-timing.json").write_text(
                json.dumps({"phases": _phase_timings, "total_seconds": round(total, 2)}, indent=2)
            )
        except Exception:
            pass

    async def _stream_phase(name: str, messages):
        """Stream a single agent phase, accumulating costs.

        Wrapped with stream_with_idle_timeout so a wedged claude_agent_sdk
        subprocess fails fast (AgentTimeoutError) instead of hanging.
        """
        nonlocal total_cost, total_turns, total_duration
        _t0 = time.perf_counter()
        # Fix #3/#4/#7 — emit authoritative progress at phase entry.
        _phase_key = _STREAM_PHASE_TO_KEY.get(name)
        if _phase_key:
            _progress.phase_start(_phase_key)
            for _pe in _drain_progress():
                yield _pe
        async for evt in stream_with_idle_timeout(name, output_dir, messages):
            if evt.get("event") == "agent_result":
                data = json.loads(evt["data"])
                total_cost += data.get("cost_usd", 0)
                total_turns += data.get("num_turns", 0)
                total_duration += data.get("duration_ms", 0)
            else:
                yield evt
        try:
            _elapsed = time.perf_counter() - _t0
            _phase_timings[name] = _phase_timings.get(name, 0.0) + _elapsed
            yield sse_event("log", {"text": f"[Timing] {name}: {_elapsed:.1f}s"})
        except Exception:
            pass

    # Phase 1: Contract generation
    yield sse_event("log", {"text": f"[Registry] Initialized: {len(registry['entities'])} entities, {len(registry['api_routes'])} routes"})
    yield sse_event("status", {"message": "Generating contracts..."})
    for aid in PHASE_TO_AGENTS["contract"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["contract"]))

    # Deterministic contracts are PRIMARY, LLM contract agent is FALLBACK.
    from services.contract_generator import generate_contracts
    from services.phase_gates import check_contract_completeness
    try:
        _cg = generate_contracts(output_dir, plan)
        yield sse_event("log", {"text": f"[Contract] deterministic: {len(_cg.get('generated', []))} file(s), {len(_cg.get('errors', []))} error(s)"})
    except Exception as _cgx:
        yield sse_event("log", {"text": f"[Contract] deterministic generation failed (falling back to LLM): {_cgx}"})

    _contract_precheck = check_contract_completeness(output_dir, plan)
    if _contract_precheck["passed"]:
        yield sse_event("log", {"text": "[Contract] deterministic contracts complete — skipping LLM agent"})
    else:
        async for evt in _stream_phase("Contract", run_contract_agent(output_dir, plan, domain_context=domain_ctx)):
            yield evt
    for aid in PHASE_TO_AGENTS["contract"]:
        yield sse_event("office", agent_complete_event(aid))

    # --- CONTRACT GATE: verify contracts cover every entity from plan ---
    contract_gate = check_contract_completeness(output_dir, plan)
    if not contract_gate["passed"]:
        gap_count = len(contract_gate["missing"])
        yield sse_event("log", {"text": f"[Contract Gate] {gap_count} gaps found — sending back to contract agent"})
        yield sse_event("status", {"message": f"Completing contracts ({gap_count} gaps)..."})
        try:
            async for evt in _stream_phase("Contract-Fix", run_contract_agent(output_dir, plan, domain_context=domain_ctx)):
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
        from services.contract_generator import ensure_approval_bindings
        _eb = ensure_approval_bindings(output_dir, plan)
        if _eb["added"]:
            yield sse_event("log", {"text": f"[Contract] approval start-bindings: added {_eb['added']} <entity>_created binding(s)"})
    except Exception as _ebx:
        yield sse_event("log", {"text": f"[Contract] approval-binding patch skipped: {_ebx}"})

    # Handoff: contract → schema
    yield sse_event("office", agent_handoff_event("contract_writer", "schema_designer", artifact="contracts"))

    # Inject register + cta_hierarchy into design-spec.json (Figma pipeline — spec was written
    # by Figma context, not the Design Agent, so it may not have these fields yet).
    # Always set both unconditionally so they stay in sync.
    # Use the LLM-driven classifier (same as the normal pipeline) for consistency.
    from agents.planner import classify_register_llm as _classify_register_llm
    from agents.design_agent import save_design_spec as _save_design_spec
    from services.cta_defaults import defaults_for_register as _defaults_for_register_figma
    _spec_path_figma = Path(output_dir) / "src" / "contracts" / "design-spec.json"
    _figma_register = plan.get("register") or await _classify_register_llm(
        description, plan.get("domain", ""), plan
    )
    if _spec_path_figma.exists():
        try:
            _figma_spec = json.loads(_spec_path_figma.read_text())
            _figma_spec["register"] = _figma_register
            _figma_spec["cta_hierarchy"] = _defaults_for_register_figma(_figma_register)
            _save_design_spec(output_dir, _figma_spec, plan=plan)
            yield sse_event("log", {"text": f"[Design] Register injected: {_figma_register}"})
        except Exception:
            pass

    # --- Compile design-spec → tokens.custom.json ---
    # This runs deterministically (no LLM), so it's fast and idempotent.
    # Schema agents that fire after this point see project-tuned tokens.
    # Task 36: gated behind FIDELITY_MODE_ENABLED flag.
    if FIDELITY_MODE_ENABLED:
        try:
            from services.design_compiler import compile_to_file
            spec_path = Path(output_dir) / "src" / "contracts" / "design-spec.json"
            if spec_path.exists():
                design_spec_for_tokens = json.loads(spec_path.read_text())
                tokens_path = Path(output_dir) / "src" / "theme" / "tokens.custom.json"
                compile_to_file(design_spec_for_tokens, str(tokens_path))
                yield sse_event("log", {"text": f"[Tokens] ✓ Compiled tokens.custom.json from design-spec"})
            else:
                yield sse_event("log", {"text": f"[Tokens] No design-spec.json found at {spec_path}; skipping compile"})
        except Exception as e:
            logger.exception("[Tokens] design_compiler failed")
            yield sse_event("log", {"text": f"[Tokens] ⚠ Compile failed (non-fatal): {e}"})
    else:
        yield sse_event("log", {"text": "[Tokens] FIDELITY_MODE_ENABLED=false — skipping design_compiler step"})

    # FIGMA-FLOOR: copy the app-foundation floor into the generated app. The
    # text pipeline (_run_relay_pipeline) does this in its own phase; the
    # Figma pipeline historically skipped it on the theory that "Figma brings
    # its own pages" — which is true for src/app/**/page.tsx but leaves the
    # app without src/db/index.ts, src/lib/schema-page.tsx, src/lib/data-engine
    # and every other runtime module (dead imports, seed.ts crash). The
    # `not target.exists()` guard below protects every Figma-authored file.
    _floor = Path(__file__).parent.parent / "templates" / "app-foundation"
    if _floor.exists():
        _dst = Path(output_dir)
        _copied = 0
        for _src_file in _floor.rglob("*"):
            if _src_file.is_file():
                _rel = _src_file.relative_to(_floor)
                _target = _dst / _rel
                if not _target.exists():
                    _target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(_src_file, _target)
                    _copied += 1
        yield sse_event("log", {"text": f"[Templates] Copied {_copied} foundation files (runtime, auth, hooks, UI)"})

    # Phase 2: Schema + config + types + npm install
    yield sse_event("status", {"message": "Building foundation (schema, config, types)..."})
    _cf = chat_flavor.start("data")
    if _cf:
        yield sse_event("message", {"text": _cf})
    for aid in PHASE_TO_AGENTS["schema"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["schema"]))
    project_short_id = Path(output_dir).name

    # Deterministic Drizzle schema + types builder is PRIMARY, LLM is FALLBACK.
    from services.schema_builder import build_schema_files
    try:
        _sb = build_schema_files(plan, output_dir)
        yield sse_event("log", {"text": f"[Schema] deterministic: {len(_sb.get('generated', []))} file(s), {len(_sb.get('errors', []))} error(s)"})
    except Exception as _sbx:
        yield sse_event("log", {"text": f"[Schema] deterministic generation failed (falling back to LLM): {_sbx}"})

    if _schema_files_complete(output_dir, plan):
        yield sse_event("log", {"text": "[Schema] deterministic schema complete — skipping LLM agent"})
    else:
        async for evt in _stream_phase("Schema", run_schema_agent(output_dir, plan, domain_context=domain_ctx, project_short_id=project_short_id)):
            yield evt
    for aid in PHASE_TO_AGENTS["schema"]:
        yield sse_event("office", agent_complete_event(aid))

    # Registry: extract actual schema entities
    extracted_entities = extract_entities_from_schema(output_dir)
    if extracted_entities:
        registry = reconcile_entities(registry, extracted_entities)
        save_registry(output_dir, registry)
        yield sse_event("log", {"text": f"[Registry] Updated entities from schema: {len(extracted_entities)} extracted"})
        _cf = chat_flavor.done("data", len(extracted_entities))
        if _cf:
            yield sse_event("message", {"text": _cf})

    # Correct the CANONICAL registry (contracts/resource-registry.json, read by
    # the page/schema agents) against the real emitted schema — its plan-derived
    # notNull/enum drift otherwise (see registry_schema_reconcile).
    try:
        _rc = reconcile_registry_to_schema(output_dir)
        logger.info(
            "resource-registry reconciled to schema: %d entities, %d columns",
            _rc["entities_reconciled"], _rc["columns_updated"],
        )
    except Exception:
        logger.exception("resource-registry schema reconcile failed (non-fatal)")

    # Deliverable previews — data models (drives the live tracker + preview cards).
    try:
        from services.progress_events import iter_entities as _iter_entities
        for _rev in _iter_entities(output_dir):
            yield sse_event("resource", _rev)
    except Exception:
        pass

    # Handoff: schema → parallel agents
    yield sse_event("office", agent_handoff_event("schema_designer", "api_generator", artifact="schema.prisma"))

    # Phase 3: Parallel — auth + API + business logic
    yield sse_event("status", {"message": "Generating auth, API routes, and business logic..."})

    parallel_agents: list[tuple[str, any]] = [
        ("API", lambda: run_api_agent(output_dir, plan, domain_context=domain_ctx)),
    ]

    parallel_agent_ids = ["api_generator"]

    if plan.get("workflows"):
        parallel_agents.append(
            ("BusinessLogic", lambda: run_business_logic_agent(output_dir, plan, domain_context=domain_ctx))
        )
        parallel_agent_ids.append("bizlogic_agent")
        yield sse_event("office", agent_handoff_event("schema_designer", "bizlogic_agent", artifact="schema.prisma"))
        _cf = chat_flavor.start("workflows")
        if _cf:
            yield sse_event("message", {"text": _cf})

    yield sse_event("office", parallel_start_event(parallel_agent_ids))
    for aid in parallel_agent_ids:
        phase_key = {"api_generator": "api", "bizlogic_agent": "business_logic"}.get(aid, "api")
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM[phase_key]))

    async for evt in run_parallel_agents(output_dir, parallel_agents):
        if evt.get("event") == "agent_result":
            data = json.loads(evt["data"])
            total_cost += data.get("cost_usd", 0)
            total_turns += data.get("num_turns", 0)
            total_duration += data.get("duration_ms", 0)
        else:
            yield evt

    for aid in parallel_agent_ids:
        yield sse_event("office", agent_complete_event(aid))

    if plan.get("workflows"):
        _cf = chat_flavor.done("workflows", len(plan.get("workflows") or []))
        if _cf:
            yield sse_event("message", {"text": _cf})

    # COMPLETENESS (working-app): the api agent often wedges at the 600s timeout, leaving
    # most entities with a DB schema but NO routes — so the app can't list/create them.
    # Fill every missing CRUD route set deterministically from the schema files. This is
    # non-destructive (keeps any LLM-written route) and can't time out, so it runs BEFORE
    # the API gate — which then passes without an expensive LLM re-run.
    try:
        from services.crud_route_generator import ensure_api_routes
        _filled = ensure_api_routes(output_dir)
        if _filled:
            yield sse_event("log", {"text": f"[API] deterministic CRUD fill: wrote {len(_filled)} missing route file(s)"})
    except Exception as _cre:
        yield sse_event("log", {"text": f"[API] crud route fill skipped: {_cre}"})

    # Registry: extract actual API routes
    extracted_routes = extract_routes_from_files(output_dir)
    if extracted_routes:
        registry = merge_section(registry, "api_routes", extracted_routes)
        save_registry(output_dir, registry)
        yield sse_event("log", {"text": f"[Registry] Updated routes: {len(extracted_routes)} extracted"})

    # Validate registry after schema + routes
    reg_errors = validate_registry(registry)
    if reg_errors:
        report = format_validation_report(reg_errors)
        yield sse_event("log", {"text": f"[Registry] {report}"})
        yield sse_event("registry_validation", {"phase": "post_api", "errors": [{"section": e.section, "name": e.name, "error": e.error, "suggestion": e.suggestion, "severity": e.severity} for e in reg_errors]})

    # Handoff: parallel agents → Figma UI
    yield sse_event("office", agent_handoff_event("api_generator", "component_builder", artifact="api_routes"))

    # --- AUTH GATE (Figma pipeline) ---
    from services.phase_gates import check_auth_completeness
    auth_gate = check_auth_completeness(output_dir)
    if not auth_gate["passed"]:
        issue_count = len(auth_gate["issues"])
        yield sse_event("log", {"text": f"[Auth Gate] {issue_count} auth issues — fixing"})
        yield sse_event("status", {"message": f"Fixing auth layer ({issue_count} issues)..."})
        try:
            # Auth handled by templates — re-copy if missing
            template_dir = Path(__file__).parent.parent / "templates" / "app-foundation"
            for auth_file in ["src/auth.ts", "src/middleware.ts", "src/app/api/auth/[...nextauth]/route.ts", "src/app/api/auth/signup/route.ts"]:
                src = template_dir / auth_file
                dst = Path(output_dir) / auth_file
                if src.exists() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    # `shutil` is imported at the top of this function.
                    shutil.copy2(src, dst)
            # Yield a dummy event to satisfy the async for
            async for evt in _stream_phase("Auth-Fix", _empty_stream()):
                yield evt
        except Exception as e:
            yield sse_event("log", {"text": f"[Auth Gate] Fix failed: {e}"})
    else:
        yield sse_event("log", {"text": "[Auth Gate] ✓ Auth layer complete"})

    # --- RULES AGENT (Figma pipeline) — convert planner prose into ProjectRules ---
    # Must run BEFORE runtime injection so the exporter ships rules/index.json.
    # The Figma path historically skipped this, so Figma-generated apps had NO
    # business rules end-to-end. Non-fatal.
    try:
        from agents.rules_agent import run_rules_agent
        yield sse_event("status", {"message": "Generating business rules..."})
        _rules = await run_rules_agent(
            output_dir, plan, domain_context=domain_ctx,
            project_id=project_id if project_id else None,
        )
        _suffix = " (synced to DB)" if project_id and _rules else ""
        yield sse_event("log", {"text": f"[Rules] Generated {len(_rules)} rule(s) from planner intent{_suffix}"})
    except Exception as e:
        logger.exception("[Rules] Figma agent failed")
        yield sse_event("log", {"text": f"[Rules] ⚠ Generation failed (non-fatal): {e}"})

    # --- RUNTIME INJECTION (Figma pipeline) — always inject ---
    try:
        from services.runtime_injector import inject_runtime
        rt_result = inject_runtime(output_dir, app_name=(plan.get("appName") or plan.get("module_name") or plan.get("name")), domain=plan.get("domain"), project_id=str(project_id) if project_id else None)
        yield sse_event("log", {"text": f"[Runtime] Injected: {len(rt_result.get('copied', []))} files"})
    except Exception as e:
        yield sse_event("log", {"text": f"[Runtime] Injection failed: {e}"})

    # Same integrations sync as the text pipeline — Figma-generated apps also
    # need MCP/env credentials from the org's platform_integrations rows.
    if project_id is not None:
        try:
            from database import async_session
            from models.project import Project
            from services.env_writer import write_env_local_from_platform
            async with async_session() as _db:
                _proj = await _db.get(Project, project_id)
                if _proj is not None and _proj.org_id is not None:
                    _iw = await write_env_local_from_platform(output_dir, _proj.org_id, _db)
                    _keys = _iw.get("set", []) or []
                    _mcp_n = _iw.get("mcp_servers", 0)
                    if _keys or _mcp_n:
                        yield sse_event("log", {
                            "text": f"[Integrations] Synced .env.local: {len(_keys)} key(s), {_mcp_n} MCP server(s)"
                        })
        except Exception as e:
            yield sse_event("log", {"text": f"[Integrations] Sync skipped: {e}"})

    # Prune per-app artifacts that bypass the injected engines — the Data Engine
    # catch-all serves all entity CRUD, and the workflow engine (+ standard
    # /api/workflows API) is the single path for domain logic. Deletes per-entity
    # CRUD/action routes and imperative src/services/*.ts.
    try:
        from services.api_route_prune import prune_entity_crud_routes
        _pruned = prune_entity_crud_routes(output_dir)
        if _pruned["deleted"] or _pruned["deleted_actions"] or _pruned["deleted_services"]:
            yield sse_event("log", {"text": f"[API] pruned {len(_pruned['deleted'])} CRUD route(s), {len(_pruned['deleted_actions'])} bypass action-route(s), {len(_pruned['deleted_services'])} TS service(s) → engines are the single execution path"})
    except Exception as _pe:
        yield sse_event("log", {"text": f"[API] route prune skipped: {_pe}"})

    # Phase 4+5: Figma UI (Schema path, IR path, or LLM path)
    # The deterministic Figma mapper already ran at the top of this function;
    # its emitted routes are in `deterministic_pages` and the LLM schema
    # pipeline below skips them via skip_routes.
    from services.schema_pipeline import SCHEMA_MODE_ENABLED, run_schema_frontend_pipeline
    from services.ir_pipeline import IR_FRONTEND_ENABLED

    if SCHEMA_MODE_ENABLED:
        # ── SCHEMA PATH: emit JSON Page schemas (Phase 4) ──
        # Recalibrate the progress tracker with the plan's real counts —
        # same reason as the LLM pipeline: a fixed 120s frontend_schema
        # baseline lies about the ETA on any non-toy app.
        try:
            _progress.recalibrate(
                pages=len(plan.get("pages") or []),
                entities=len(plan.get("entities") or []),
                workflows=len(plan.get("workflows") or []),
                parallelism=int(os.getenv("FORGE_PAGE_CONCURRENCY", "5") or "5"),
            )
            for _pe in _drain_progress():
                yield _pe
        except Exception:
            pass
        # Skip the LLM schema pipeline entirely when the deterministic Figma
        # mapper already emitted every page the plan asked for. We compare
        # counts (not slugs) because the deterministic mapper's slug is
        # derived from the Figma frame name, which may differ from plan.pages
        # slugs — but if the counts match, every plan page is covered by one
        # deterministic emit.
        plan_page_count = len(plan.get("pages") or [])
        if deterministic_pages and plan_page_count > 0 and len(deterministic_pages) >= plan_page_count:
            yield sse_event("log", {
                "text": f"[Pipeline] Deterministic mapper covered all {plan_page_count} plan page(s) — skipping LLM schema pipeline"
            })
        else:
            yield sse_event("status", {"message": "Generating frontend via schema agent..."})
            yield sse_event("log", {"text": "[Pipeline] Using schema-mode (default — Phase 4)"})
            if deterministic_pages:
                yield sse_event("log", {
                    "text": f"[Pipeline] Deterministic mapper covered {len(deterministic_pages)}/{plan_page_count} pages — LLM fills the rest"
                })
            try:
                async for evt in run_schema_frontend_pipeline(
                    output_dir, plan, description, domain_context=domain_ctx,
                    skip_routes=deterministic_pages,   # pages already emitted by Figma mapper
                ):
                    yield evt
            except Exception as e:
                import traceback
                logger.exception("[Pipeline] Schema pipeline failed: %s", e)
                yield sse_event("log", {"text": f"[Pipeline] ⚠ Schema pipeline error: {e}"})
                yield sse_event("log", {"text": f"[Pipeline] Traceback: {traceback.format_exc()[:500]}"})

        # --- CTA HIERARCHY GATE: detect + log only (no retry loop yet) ---
        try:
            from services.phase_gates import check_cta_hierarchy
            cta_gate = check_cta_hierarchy(output_dir, plan)
            if not cta_gate["passed"]:
                yield sse_event("log", {
                    "text": f"[CTA Gate] {len(cta_gate['issues'])} issues — flagging only (no auto-retry in this iteration)"
                })
                for issue in cta_gate["issues"][:10]:
                    yield sse_event("log", {"text": f"[CTA Gate]   - {issue}"})
            else:
                yield sse_event("log", {"text": "[CTA Gate] ✓ All schemas satisfy CTA hierarchy"})
        except Exception as e:
            yield sse_event("log", {"text": f"[CTA Gate] check failed: {e}"})

        # --- PROGRESSIVE DISCLOSURE GATE: detect + log only (matches CTA scope) ---
        try:
            from services.phase_gates import check_progressive_disclosure
            pd_gate = check_progressive_disclosure(output_dir, plan)
            if not pd_gate["passed"]:
                yield sse_event("log", {
                    "text": f"[PD Gate] {len(pd_gate['issues'])} issues — flagging only (no auto-retry in this iteration)"
                })
                for issue in pd_gate["issues"][:10]:
                    yield sse_event("log", {"text": f"[PD Gate]   - {issue}"})
            else:
                yield sse_event("log", {"text": "[PD Gate] ✓ All forms satisfy progressive disclosure"})
        except Exception as e:
            yield sse_event("log", {"text": f"[PD Gate] check failed: {e}"})

        # --- COVERAGE GATE: every plan.pages route must have a schema on disk ---
        try:
            from services.phase_gates import check_pages_coverage
            cov = check_pages_coverage(output_dir, plan)
            if not cov["passed"]:
                yield sse_event("log", {
                    "text": f"[Coverage Gate] {len(cov['missing'])} page(s) missing schema: {cov['missing']}"
                })
            else:
                yield sse_event("log", {"text": "[Coverage Gate] ✓ Every plan.pages route has a schema"})
        except Exception as e:
            yield sse_event("log", {"text": f"[Coverage Gate] check failed: {e}"})

        # Schema-mode skips QA/validator/indexer — they expect TSX artifacts.
        # Future Phase 6 work: schema-aware QA + validation.
        yield sse_event("log", {"text": "[Pipeline] Schema mode — skipping QA/validator/indexer (expect TSX artifacts)"})
        # Inject photoUrl / backgroundImage from design_spec.entityPhotos
        try:
            from services.post_emit_photo_injector import inject_photos_into_dir
            spec_path = Path(output_dir) / "src" / "contracts" / "design-spec.json"
            if spec_path.exists():
                spec = json.loads(spec_path.read_text())
                entity_photos = spec.get("entityPhotos") or {}
                if entity_photos:
                    n = inject_photos_into_dir(output_dir, entity_photos)
                    if n > 0:
                        yield sse_event("log", {"text": f"[Photos] Injected photo URLs into {n} page schema(s)"})
        except Exception as _ex:
            yield sse_event("log", {"text": f"[Photos] Injection skipped: {_ex}"})
        # Build nav-flow.json from plan.pages + transitions extracted from
        # the emitted schemas (photo injection has already finalised them).
        try:
            from services.nav_flow_emitter import emit_nav_flow
            emit_nav_flow(output_dir, plan)
            yield sse_event("log", {"text": "[NavFlow] nav-flow.json written"})
        except Exception as _nf_ex:
            yield sse_event("log", {"text": f"[NavFlow] Skipped: {_nf_ex}"})
        # Emit the standalone Next.js app skeleton so the project is
        # a runnable npm-install-able Next.js app. Idempotent — does
        # not overwrite the LLM-generated schemas / design-spec / globals.css.
        try:
            from services.app_emitter import emit_standalone_app
            from pathlib import Path as _P
            emit_standalone_app(output_dir=output_dir, project_short_id=_P(output_dir).name)
            yield sse_event("log", {"text": "[Emitter] Standalone Next.js app skeleton written"})
        except Exception as _emit_exc:
            yield sse_event("log", {"text": f"[Emitter] Skipped: {_emit_exc}"})
        # npm install off the LLM: the deterministic schema path skips the LLM
        # schema agent that used to run it. package.json now exists (emitter +
        # schema files written above), so install deps here. Idempotent.
        async for _npm_evt in _run_npm_install(output_dir):
            yield _npm_evt
        # Fidelity scoring still runs against the rendered scaffold — pages
        # exist as JSON schemas and the scaffold renders them live.
        try:
            async for evt in _stream_fidelity_scoring(output_dir, plan):
                yield evt
        except Exception as e:
            yield sse_event("log", {"text": f"[Fidelity] Pipeline skipped: {e}"})
        # Deterministic guard suite. Schema mode skips QA/validator/indexer (they
        # expect TSX), but post_generate_fixes operates on the JSON schemas + config
        # that schema mode DOES produce — check-constraint sql``, next.config jsdom
        # externalization, table row→detail nav, FK types/labels, border coherence,
        # CRUD-route/button wiring, etc. It was previously unreachable (the early
        # return below skipped it), so schema-mode apps shipped with every one of
        # those gaps. Run it here before finishing.
        try:
            _pgf_n = apply_post_generate_fixes(output_dir)
            yield sse_event("log", {"text": f"[Pipeline] post-generate guards applied ({_pgf_n} fix(es))"})
        except Exception as _pgf_ex:
            yield sse_event("log", {"text": f"[Pipeline] post-generate guards skipped: {_pgf_ex}"})
        # IRF-M5-T9: persist verify_history + edit_history so Smith turns
        # can consume them across sessions. Best-effort — a persistence
        # failure is telemetry loss, not a pipeline failure. The NameError
        # branch fires on the figma path when the T2-lite setup wasn't
        # threaded (harmless — it silently no-ops).
        try:
            from services.session_context import (
                current as _sc_current,
                persist_history as _sc_persist,
            )
            _sc_ctx_now = _sc_current()
            if _sc_ctx_now is not None:
                _sc_persist(_sc_ctx_now, output_dir)
        except Exception:  # noqa: BLE001
            pass
        yield sse_event("message", {"text": chat_flavor.ready()})
        _write_timing()
        _progress.finalize()
        for _pe in _drain_progress():
            yield _pe
        yield sse_event("log", {"text": f"[Timing] total: {sum(_phase_timings.values()):.1f}s — generation-timing.json written"})
        yield sse_event("office", build_success_event())
        yield sse_event("agent_result", {
            "num_turns": total_turns,
            "cost_usd": total_cost,
            "duration_ms": total_duration,
        })
        return
    elif IR_FRONTEND_ENABLED and source.is_figma:
        # ── IR PATH: Figma → IR Agent → compile ──
        yield sse_event("status", {"message": "Converting Figma design to IR..."})
        yield sse_event("log", {"text": "[IR] Using Figma → IR path"})

        from services.ir_figma_pipeline import run_figma_ir_pipeline

        ir_cost = 0.0
        ir_turns = 0
        ir_duration = 0

        async for evt in run_figma_ir_pipeline(output_dir, plan, description, figma_url, figma_token):
            if evt.get("event") == "agent_result":
                data = json.loads(evt["data"])
                ir_cost += data.get("cost_usd", 0)
                ir_turns += data.get("num_turns", 0)
                ir_duration += data.get("duration_ms", 0)
            else:
                yield evt

        total_cost += ir_cost
        total_turns += ir_turns
        total_duration += ir_duration

        # Extract and register
        extracted_components = extract_components_from_files(output_dir)
        if extracted_components:
            registry = merge_section(registry, "components", extracted_components)
        extracted_pages = extract_pages_from_files(output_dir)
        if extracted_pages:
            registry = merge_section(registry, "pages", extracted_pages)
        save_registry(output_dir, registry)
    elif not source.is_figma:
        yield sse_event("log", {"text": f"[Pipeline] no legacy UI path for provider {source.provider!r} — schema mode only"})
    else:
        # ── LLM PATH: Original Figma UI agent ──
        yield sse_event("status", {"message": "Generating UI from Figma design..."})
        for aid in PHASE_TO_AGENTS["components"] + PHASE_TO_AGENTS["pages"]:
            yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["components"]))
        async for evt in _stream_phase(
            "FigmaUI",
            run_figma_ui_agent(output_dir, plan, figma_url, figma_token),
        ):
            yield evt
        for aid in PHASE_TO_AGENTS["components"] + PHASE_TO_AGENTS["pages"]:
            yield sse_event("office", agent_complete_event(aid))

        # Registry: extract actual components
        extracted_components = extract_components_from_files(output_dir)
        if extracted_components:
            registry = merge_section(registry, "components", extracted_components)
            save_registry(output_dir, registry)
            yield sse_event("log", {"text": f"[Registry] Updated components: {len(extracted_components)} extracted"})

        # Registry: extract actual pages
        extracted_pages = extract_pages_from_files(output_dir)
        if extracted_pages:
            registry = merge_section(registry, "pages", extracted_pages)
            save_registry(output_dir, registry)
            yield sse_event("log", {"text": f"[Registry] Updated pages: {len(extracted_pages)} extracted"})

        # Full registry validation before QA
        reg_errors = validate_registry(registry)
        if reg_errors:
            report = format_validation_report(reg_errors)
            yield sse_event("log", {"text": f"[Registry] Pre-QA validation: {report}"})
            yield sse_event("registry_validation", {"phase": "pre_qa", "errors": [{"section": e.section, "name": e.name, "error": e.error, "suggestion": e.suggestion, "severity": e.severity} for e in reg_errors]})

            # Registry mismatches are reported — the QA agent will fix them

    # Deterministic CRUD workflows — Create/Update/Delete<Entity> so action
    # buttons have a real workflow to dispatch (idempotent; won't clobber
    # domain workflows).
    try:
        from services.crud_workflow_generator import generate_crud_workflows
        _crud_plan = plan if (plan or {}).get("entities") else {"entities": (registry or {}).get("entities") or {}}
        _crud_written = generate_crud_workflows(_crud_plan, output_dir)
        if _crud_written:
            yield sse_event("log", {"text": f"[CRUD] generated {len(_crud_written)} workflow(s): {', '.join(_crud_written[:6])}"})
    except Exception as _crud_ex:
        yield sse_event("log", {"text": f"[CRUD] generation skipped: {_crud_ex}"})

    # Deliverable previews — workflows (domain workflows first, then CRUD rollup).
    try:
        from services.progress_events import iter_workflows as _iter_workflows
        for _rev in _iter_workflows(output_dir):
            yield sse_event("resource", _rev)
    except Exception:
        pass

    # Seed is NOT executed at generation time. See the equivalent block in
    # the text pipeline for the full rationale — runtime injector copies
    # seed.ts, generated app's start.sh runs it at boot.

    # Phase 6.5: Completeness validation — find gaps before QA
    from services.completeness_validator import validate_completeness, format_issues_for_agent
    completeness_issues = validate_completeness(output_dir)
    completeness_report = format_issues_for_agent(completeness_issues)
    if completeness_issues:
        critical_count = sum(1 for i in completeness_issues if i["severity"] == "critical")
        yield sse_event("log", {"text": f"[Completeness] Found {critical_count} critical issues, {len(completeness_issues) - critical_count} warnings"})
    else:
        yield sse_event("log", {"text": "[Completeness] All checks passed"})

    _progress.phase_start("qa")
    for _pe in _drain_progress():
        yield _pe
    # Phase 7: QA verification — includes completeness issues
    yield sse_event("status", {"message": "Running QA verification..."})
    for aid in PHASE_TO_AGENTS["qa"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["qa"]))
    async for evt in _stream_phase("QA", run_qa_agent(output_dir, plan, domain_context=domain_ctx, extra_context=completeness_report)):
        yield evt
    for aid in PHASE_TO_AGENTS["qa"]:
        yield sse_event("office", agent_complete_event(aid))

    # Clear stale build cache
    apply_post_generate_fixes(output_dir)

    # ── CODER → REVIEWER → CODER CYCLE ──
    # Profile-driven: Fast caps the build-fix loop (2), Complete is thorough (5).
    # Each cycle can run a real npm build + LLM fix (minutes), so this is one of
    # the biggest fast-vs-deep levers. Exits early the moment the build is clean.
    _gp = _gen_profile(output_dir)
    MAX_REVIEW_CYCLES = _gp.review_cycles if _gp else 5
    build_ok = False  # authoritative: set only by a real `npm run build` exit 0

    for cycle in range(MAX_REVIEW_CYCLES):
        cycle_label = f"cycle {cycle + 1}/{MAX_REVIEW_CYCLES}"
        yield sse_event("status", {"message": f"Build review ({cycle_label})..."})
        yield sse_event("office", agent_handoff_event("qa_tester", "validator", artifact="code"))

        # REVIEWER: validator scans and reports bugs
        for aid in PHASE_TO_AGENTS["validation"]:
            yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["validation"]))

        collected_validator_text: list[str] = []
        async for evt in _stream_phase("Validator", run_validator(output_dir, domain=domain_label, description=description)):
            event_type = evt.get("event")
            if event_type in ("log", "message"):
                data = json.loads(evt["data"]) if isinstance(evt.get("data"), str) else evt.get("data", {})
                text = data.get("text", "")
                if text:
                    collected_validator_text.append(text)
            yield evt

        for aid in PHASE_TO_AGENTS["validation"]:
            yield sse_event("office", agent_complete_event(aid))

        # Check if build passed
        validator_output = "\n".join(collected_validator_text)
        build_passed = any(kw in validator_output.lower() for kw in [
            "build: pass", '"pass"', "zero errors", "compiled successfully", "build passed",
        ])
        has_errors = any(kw in validator_output.lower() for kw in [
            "syntax error", "module not found", "unexpected token", "failed to compile",
        ])

        # Authoritative build gate: the keyword scan above is only a HINT — the
        # real `npm run build` exit code decides. We never break "clean" on a
        # false keyword-pass, and a persistent failure is surfaced loudly instead
        # of silently shipping. The (slow) real build runs only when the heuristic
        # thinks we're done OR on the final cycle — usually 1–2 builds, not 5.
        if (build_passed and not has_errors) or cycle == MAX_REVIEW_CYCLES - 1:
            yield sse_event("status", {"message": f"Verifying real build ({cycle_label})..."})
            _ok, _errs = await _real_build_ok(output_dir)
            if _ok:
                build_ok = True
                yield sse_event("log", {"text": f"[Build] ✓ Real npm build passed on {cycle_label}"})
                break
            if cycle == MAX_REVIEW_CYCLES - 1:
                build_ok = False
                yield sse_event("log", {"text": f"[Build] ✗ Build STILL FAILING after {MAX_REVIEW_CYCLES} cycles — real errors:\n{(_errs or '(no parseable errors)')[:1500]}"})
                break
            # Heuristic said pass but the real build failed — override with the
            # ground-truth errors and keep iterating.
            yield sse_event("log", {"text": "[Build] Heuristic pass but real build FAILED — feeding real errors to the coder"})
            validator_output = _errs or validator_output

        # CODER: send bugs back to page agent to fix
        yield sse_event("log", {"text": f"[Build] Errors found — sending back to coder"})
        yield sse_event("status", {"message": f"Fixing build errors ({cycle_label})..."})

        fix_prompt = (
            f"The build reviewer found errors. Fix ALL of them:\n\n"
            f"{validator_output[-3000:]}\n\n"
            f"Read each file, fix the error, verify with `npx tsc --noEmit 2>&1 | head -30`."
        )
        try:
            async for evt in _stream_phase(
                "Build-Fix",
                run_page_agent(output_dir, plan, domain_context=domain_ctx, design_spec=design_spec, fix_prompt=fix_prompt),
            ):
                yield evt
        except Exception as e:
            yield sse_event("log", {"text": f"[Build] Fix failed: {e}"})

    # ── VISUAL REVIEW PHASE ──
    yield sse_event("status", {"message": "Visual design review..."})
    try:
        from screenshot import capture_page_screenshot, capture_key_pages
        from agent import run_design_reviewer_agent, run_fixer_agent
        from services.preview_manager import start_project_environment, stop_project_environment

        short_id = Path(output_dir).name
        env_info = await start_project_environment(short_id, output_dir, with_database=False)
        preview_port = env_info.get("port")

        if preview_port:
            MAX_VISUAL_CYCLES = 3
            for vis_cycle in range(MAX_VISUAL_CYCLES):
                yield sse_event("log", {"text": f"[Visual] Review cycle {vis_cycle + 1}/{MAX_VISUAL_CYCLES}"})

                screenshots = await capture_key_pages(output_dir, preview_port)
                if not screenshots:
                    yield sse_event("log", {"text": "[Visual] No screenshots captured — skipping"})
                    break

                all_approved = True
                all_issues: list[str] = []
                for page_info in screenshots:
                    review = await run_design_reviewer_agent(
                        output_dir, page_info["route"], page_info["screenshot"],
                        domain=domain_label, description=description,
                    )
                    if "APPROVED" in review.upper():
                        yield sse_event("log", {"text": f"[Visual] ✓ {page_info['route']} approved"})
                    else:
                        all_approved = False
                        all_issues.append(f"## {page_info['route']}\n{review}")
                        yield sse_event("log", {"text": f"[Visual] ✗ {page_info['route']} — issues found"})

                if all_approved:
                    yield sse_event("log", {"text": f"[Visual] ✓ Design approved on cycle {vis_cycle + 1}"})
                    break

                if vis_cycle == MAX_VISUAL_CYCLES - 1:
                    break

                # Send to fixer
                yield sse_event("status", {"message": f"Fixing visual issues ({vis_cycle + 1})..."})
                async for evt in stream_agent_messages(
                    run_fixer_agent(output_dir, "\n\n".join(all_issues)),
                    output_dir=output_dir, event_prefix="[Visual-Fix] ",
                ):
                    if evt.get("event") == "agent_result":
                        data = json.loads(evt["data"])
                        total_cost += data.get("cost_usd", 0)
                        total_turns += data.get("num_turns", 0)
                    else:
                        yield evt

            try:
                await stop_project_environment(short_id)
            except Exception:
                pass
        else:
            yield sse_event("log", {"text": "[Visual] Could not start preview — skipping"})
    except Exception as e:
        yield sse_event("log", {"text": f"[Visual] Review skipped: {e}"})

    # Handoff: → indexer
    yield sse_event("office", agent_handoff_event("validator", "indexer", artifact="build_output"))

    # Phase 9: Indexing
    yield sse_event("status", {"message": "Indexing application..."})
    for aid in PHASE_TO_AGENTS["indexing"]:
        yield sse_event("office", agent_start_event(aid, PHASE_TO_ROOM["indexing"]))
    async for evt in _stream_phase("Indexer", run_indexer(output_dir)):
        yield evt
    for aid in PHASE_TO_AGENTS["indexing"]:
        yield sse_event("office", agent_complete_event(aid))

    # ── FIDELITY SCORING (advisory, opt-in via env) ──
    try:
        async for evt in _stream_fidelity_scoring(output_dir, plan):
            yield evt
    except Exception as e:
        yield sse_event("log", {"text": f"[Fidelity] Pipeline skipped: {e}"})

    # ── JOURNEY GATE — mirror of the text-pipeline gate above. Same env
    # controls (FORGE_JOURNEY_GATE=off|warn|strict). Off by default.
    try:
        from services.journey_gate import run_journey_gate, JourneyGateFailure
        _journey_url = os.environ.get("FORGE_JOURNEY_BASE_URL", "http://localhost:3000")
        async for _jevt in run_journey_gate(output_dir, base_url=_journey_url):
            yield _jevt
    except JourneyGateFailure as _jgf:
        yield sse_event("error", {"error": f"journey_gate: {_jgf.summary}",
                                  "journeys": _jgf.journeys})
        raise
    except Exception as e:
        yield sse_event("log", {"text": f"[Journey] Skipped: {e}"})

    # ── BINDING GATE (Slice 1) — every UI ref must resolve to a real resource ──
    async for evt in _stream_binding_gate(output_dir):
        yield evt

    # ── AUTO-INSTALL APP AGENT from plan.agent_graph (SP4.5) ──────────
    # Same hook as _run_relay_pipeline — non-fatal auto-install of the
    # planner's agent_graph as a working src/agents/agent-service.ts.
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
                        output_dir=output_dir,
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
    except Exception:
        logger.exception("[pipeline] agent auto-install failed (non-fatal)")
        yield sse_event("log", {"text": "[Agent] auto-install skipped (see server log)"})

    # Build success
    _write_timing()
    yield sse_event("log", {"text": f"[Timing] total: {sum(_phase_timings.values()):.1f}s — generation-timing.json written"})
    yield sse_event("office", build_success_event())

    # Yield combined totals
    yield sse_event("agent_result", {
        "num_turns": total_turns,
        "cost_usd": total_cost,
        "duration_ms": total_duration,
    })


def _is_credit_error(lower_text: str) -> bool:
    """Return True only if the text specifically indicates a credit/billing issue."""
    credit_phrases = [
        "credit balance",
        "billing",
        "quota exceeded",
        "rate limit",
        "credits exhausted",
        "balance is too low",
        "insufficient credits",
        "out of credits",
        "purchase credits",
    ]
    return any(p in lower_text for p in credit_phrases)


def _unwrap_error(e: Exception) -> str:
    """Extract the root error message, unwrapping ExceptionGroups/TaskGroups and SDK errors."""
    from sse_helpers import BillingError, BILLING_ERROR_MSG

    # Fast path: BillingError is already clear
    if isinstance(e, BillingError):
        return BILLING_ERROR_MSG

    try:
        from claude_agent_sdk._errors import ProcessError
        _has_sdk = True
    except ImportError:
        ProcessError = None  # type: ignore[misc]
        _has_sdk = False

    # Unwrap ExceptionGroups first
    inner: BaseException = e
    if isinstance(e, BaseExceptionGroup):
        inner = e.exceptions[0] if e.exceptions else e
        while isinstance(inner, BaseExceptionGroup) and inner.exceptions:
            inner = inner.exceptions[0]

    msg = str(inner)

    _credit_msg = "Your credit balance is too low to access the API. Please go to Plans & Billing to upgrade or purchase credits."

    # Extract meaningful message from claude_agent_sdk ProcessError
    if _has_sdk and isinstance(inner, ProcessError):
        stderr = getattr(inner, "stderr", None) or ""
        # Check if the real API error is specifically a credit/billing issue
        for text in (stderr, msg):
            if _is_credit_error(text.lower()):
                return _credit_msg
        # If stderr has useful info, use it
        if stderr and stderr != "Check stderr output for details":
            return stderr.strip()
        # Generic CLI failure — pass through the original message
        return msg if msg else "Code generation failed unexpectedly. Please try again."

    # Check for Anthropic API credit errors passed as other exception types
    if _is_credit_error(msg.lower()):
        return _credit_msg

    # Check the full exception chain for BillingError or credit keywords
    chain_exc: BaseException | None = inner
    while chain_exc is not None:
        if isinstance(chain_exc, BillingError):
            return _credit_msg
        chain_msg = str(chain_exc).lower()
        if _is_credit_error(chain_msg):
            return _credit_msg
        chain_exc = chain_exc.__cause__ or chain_exc.__context__

    return msg

# Patterns that indicate the user is approving a plan.
# Short patterns use word-boundary matching to avoid false positives
# (e.g. "yes" inside "keyes" or "analysis").
@router.post("/api/projects/{project_id}/generate")
async def generate_project(
    project_id: uuid.UUID,
    req: GenerateRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Initial generation from description/plan — streams SSE events."""
    project = await get_project_with_auth(project_id, user, db)

    # Sanitise pasted credentials — browser copy-paste frequently includes
    # trailing whitespace, which httpx then rejects when building the
    # X-Figma-Token header ("Illegal header value").
    if req.figma_token:
        req.figma_token = req.figma_token.strip()
    if req.figma_url:
        req.figma_url = req.figma_url.strip()

    # A `design` request for Figma is the same import as the two loose fields.
    _figma_credential_id: str | None = None
    if req.design is not None and req.design.provider == "figma":
        req.figma_url = req.figma_url or req.design.ref.strip()
        req.figma_token = req.figma_token or (req.design.token or "").strip()
        _figma_credential_id = req.design.credential_id

    # The Figma token comes from the org's Figma MCP-server row (Settings →
    # MCP Servers), then FIGMA_TOKEN in the environment. A token pasted into
    # the request is used for this call and never persisted. Selecting the
    # Figma pipeline never requires the secret in the request body.
    if req.figma_url and not req.figma_token:
        from services.design_import import figma_token_for as _figma_token_for
        from services.design_source import DesignSourceError as _DesignSourceError
        try:
            req.figma_token, _figma_credential_id = await _figma_token_for(
                {"credential_id": _figma_credential_id}, db=db, org_id=project.org_id,
            )
        except _DesignSourceError as _cred_exc:
            raise HTTPException(status_code=400, detail=str(_cred_exc))
        if not req.figma_token:
            # Building the plan from the prompt alone would silently drop the
            # design the user asked for; say what is missing instead.
            raise HTTPException(
                status_code=400,
                detail=(
                    "no Figma access token: register Figma under Settings → MCP Servers "
                    "(https://mcp.figma.com/mcp with a personal access token) or paste a token"
                ),
            )

    is_figma = bool(req.figma_url and req.figma_token)
    # A design from any other provider (UX Pilot today). Figma keeps its own
    # branch below because its plan comes from the design analyzer over a
    # screenshot + styles tree; the others build the plan from the adapter.
    _design_req = req.design_import()
    is_design_import = bool(_design_req and _design_req.provider != "figma")
    _design_label = {"uxpilot": "UX Pilot"}.get(_design_req.provider, _design_req.provider) if _design_req else ""
    description = req.description or (
        f"Import from Figma: {req.figma_url}" if is_figma
        else f"Import from {_design_label}: {_design_req.ref}" if is_design_import
        else ""
    )

    # When Figma is supplied but no explicit plan, build the plan directly from
    # the Figma file (one page per top-level frame). This bypasses the LLM
    # planner — Figma is authoritative for scope. Falls back to LLM planning
    # on any error so a malformed Figma doesn't break the request.
    if is_figma and not req.plan:
        try:
            from services.figma_plan_builder import build_plan_from_figma
            req.plan = await build_plan_from_figma(req.figma_url, req.figma_token)
            logger.info(
                f"[Figma Plan] Built plan with {len(req.plan.get('pages', []))} page(s) "
                f"from {req.figma_url}: {[p.get('route') for p in req.plan.get('pages', [])]}"
            )
        except Exception as _fp_ex:
            logger.warning(
                f"[Figma Plan] build_plan_from_figma failed: {_fp_ex} — "
                f"falling back to LLM planner"
            )
            # req.plan remains None; pipeline below will plan as before.

    # When no plan and no design, enter planning mode instead of generating
    needs_planning = not is_figma and not is_design_import and not req.plan

    # Update project status (planning keeps 'generating' so frontend routes subsequent messages to /chat)
    project.status = ProjectStatus.generating
    project.description = description
    await db.commit()

    # Store user message
    user_msg = Conversation(
        project_id=project.id,
        role=MessageRole.user,
        content=description,
        message_type=MessageType.generation,
    )
    db.add(user_msg)
    await db.commit()

    async def event_stream():
        # If no plan provided and not Figma, start with domain DISCOVERY
        # (the planner will run later, AFTER the user approves the dossier
        # — that way the plan benefits from researched entity hints and
        # compliance regimes).
        if needs_planning:
            try:
                yield sse_event("intent", {"intent": "DISCOVERY", "reasoning": "Researching your domain before drafting a plan"})
                yield sse_event("status", {"message": "Researching domain context..."})
                yield sse_event("discovery_started", {"description": description[:200]})

                from agents.domain_agent import run_domain_discovery
                try:
                    dossier = await run_domain_discovery(
                        description, plan=None, enable_web_search=True,
                    )
                except Exception as _dx:
                    logger.exception("[generate] discovery agent failed: %s", _dx)
                    yield sse_event("log", {
                        "text": f"[Discovery] ⚠ FAILED: {_dx} — please retry or refine your description",
                    })
                    yield sse_event("complete", {"project_id": str(project.id)})
                    return

                _save_pending_discovery(project.output_dir, dossier)
                # Blueprint hook (spec §6.3) — write the domain into the
                # blueprint as Smith authored it, not backfilled. Safe:
                # any failure is swallowed by the hook.
                try:
                    from services.blueprint_pipeline_hooks import record_discovery as _record_discovery
                    _bp_dossier = dict(dossier) if isinstance(dossier, dict) else {}
                    _bp_dossier.setdefault("user_prompt", req.description or description)
                    _record_discovery(
                        output_dir=project.output_dir,
                        project_id=str(project.id),
                        dossier=_bp_dossier,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("[blueprint] discovery hook failed")
                await _persist_assistant_message(
                    project.id,
                    "I researched your domain. Review the dossier and tweak "
                    "anything before I draft the plan.",
                    MessageType.chat,
                    metadata={"discovery": dossier, "intent": "DISCOVERY"},
                )
                yield sse_event("discovery_complete", dossier)
                yield sse_event("discovery_approval_needed", {
                    "editable_fields": sorted(_DISCOVERY_EDITABLE_KEYS),
                    "signal": "[APPROVE_DISCOVERY]",
                    "instruction": (
                        "Review the dossier. Send `[APPROVE_DISCOVERY]` to "
                        "continue to planning, or `[APPROVE_DISCOVERY] {\"domain\": \"…\", "
                        "\"complianceNotes\": [\"…\"]}` with edits."
                    ),
                })
                yield sse_event("complete", {"project_id": str(project.id), "intent": "DISCOVERY"})
            except Exception as e:
                logger.exception("Planning error in /generate")
                yield sse_event("error", {"message": _unwrap_error(e)})
            finally:
                # Planning phase complete — keep status as "generating" so
                # frontend routes follow-up messages to /chat, but this is
                # intentional (status transitions to "ready" after approval).
                pass
            return

        yield sse_event("status", {
            "message": (
                "Fetching Figma design..." if is_figma
                else f"Fetching {_design_label} design..." if is_design_import
                else "Starting code generation..."
            ),
            "project_id": str(project.id),
        })

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            if is_figma:
                # Figma import: Phase 1 — prefetch data, then analyze design for requirements
                from agent import _prefetch_figma_data

                parsed = parse_figma_url(req.figma_url)
                prefetch_info = await _prefetch_figma_data(
                    file_key=parsed["file_key"],
                    node_id=parsed.get("node_id"),
                    output_dir=project.output_dir,
                    figma_token=req.figma_token,
                )
                # Extract design tokens and persist as figma-context.json
                from services.figma_context import extract_figma_context
                extract_figma_context(project.output_dir, req.figma_url)

                frames = prefetch_info.get("frames_processed", [])
                yield sse_event("status", {
                    "message": f"Fetched {len(frames)} frame(s). Analyzing design...",
                })
                yield sse_event("intent", {"intent": "DESIGN_ANALYSIS", "reasoning": "Analyzing Figma design to generate requirements"})

                # Run design analyzer instead of immediate code generation
                from agents.design_analyzer import run_design_analyzer
                collected_text: list[str] = []

                async for evt in stream_agent_messages(
                    run_design_analyzer(
                        output_dir=project.output_dir,
                        figma_url=req.figma_url,
                    ),
                    output_dir=project.output_dir,
                    as_messages=True,
                ):
                    if evt.get("event") == "message":
                        data = json.loads(evt["data"]) if isinstance(evt.get("data"), str) else evt.get("data", {})
                        collected_text.append(data.get("text", ""))
                    if evt.get("event") == "agent_result":
                        pass
                    else:
                        yield evt

                full_text = "\n".join(collected_text)
                plan = _extract_plan_json(full_text)

                metadata: dict = {
                    "intent": "DESIGN_ANALYSIS",
                    "figma_url": req.figma_url,
                    # The token is resolved again at approval time from the
                    # credential row (or FIGMA_TOKEN); it is never persisted.
                    "design": {
                        "provider": "figma",
                        "ref": req.figma_url,
                        "credential_id": _figma_credential_id,
                    },
                }
                if plan:
                    metadata["plan"] = plan
                    # Emit design templates BEFORE plan_ready so the whole
                    # interactive step (themes + the plan's Begin Quest button)
                    # lands together and the stream is about to `complete` — the
                    # Begin Quest button is enabled immediately instead of being
                    # disabled for the seconds of template research after it
                    # appeared (the "click 4-5 times before it takes" bug).
                    async for _tev in _offer_design_templates(plan, project.output_dir):
                        yield _tev
                    yield sse_event("plan_ready", {"plan": plan})
                    _bp_record_plan(project, plan)

                await _persist_assistant_message(
                    project.id,
                    full_text,
                    MessageType.plan if plan else MessageType.chat,
                    metadata=metadata,
                )

                yield sse_event("complete", {"project_id": str(project.id), "intent": "DESIGN_ANALYSIS"})
                return

            elif is_design_import:
                # Design import from a provider adapter (UX Pilot): the
                # adapter's scope is the plan, its tokens are the design
                # context, and the plan goes to the user for approval the
                # same way a Figma analysis does. The key is resolved from
                # the org's MCP-server row for this request and never stored.
                from services.design_import import (
                    import_design_plan, page_texts, resolve_design,
                )
                from services.design_source import DesignSourceError
                from database import async_session as _async_session

                yield sse_event("intent", {"intent": "DESIGN_ANALYSIS",
                                           "reasoning": f"Importing the {_design_label} design"})
                try:
                    async with _async_session() as _dsess:
                        resolved = await resolve_design(
                            provider=_design_req.provider,
                            ref=_design_req.ref,
                            db=_dsess,
                            org_id=project.org_id,
                            credential_id=_design_req.credential_id,
                        )
                    plan = await import_design_plan(resolved.source, project.output_dir, description)
                except DesignSourceError as _dse:
                    logger.warning("[design] import failed: %s", _dse)
                    yield sse_event("error", {"message": f"{_design_label} import failed: {_dse}"})
                    yield sse_event("complete", {"project_id": str(project.id), "intent": "DESIGN_ANALYSIS"})
                    return

                _routes = [p.get("route") for p in plan.get("pages") or []]
                yield sse_event("status", {
                    "message": f"Imported {len(_routes)} page(s) from {_design_label}. Wiring data and actions...",
                })
                # Binding intent from the pages' visible text — the same
                # analysis the Figma plan gets from frame text. Best effort.
                try:
                    from services.figma_plan_binding import (
                        enrich_plan_with_bindings_from_texts, make_anthropic_call_llm,
                    )
                    _texts = await page_texts(resolved.source, plan)
                    plan = await enrich_plan_with_bindings_from_texts(
                        plan, _texts, call_llm=make_anthropic_call_llm(),
                    )
                except Exception as _enr_ex:  # noqa: BLE001
                    logger.warning("[design] binding enrichment skipped: %s", _enr_ex)

                metadata: dict = {
                    "intent": "DESIGN_ANALYSIS",
                    "design": resolved.metadata,
                    "original_prompt": description,
                    "plan": plan,
                }
                async for _tev in _offer_design_templates(plan, project.output_dir):
                    yield _tev
                yield sse_event("plan_ready", {"plan": plan})
                _bp_record_plan(project, plan)
                _summary = (
                    f"Imported {len(_routes)} page(s) from {_design_label}: "
                    + ", ".join(str(r) for r in _routes)
                )
                await _persist_assistant_message(
                    project.id, _summary, MessageType.plan, metadata=metadata,
                )
                yield sse_event("complete", {"project_id": str(project.id), "intent": "DESIGN_ANALYSIS"})
                return

            else:
                # Standard description-based generation — relay pipeline
                active_plan = req.plan or {}

                # ── PEER PATCHER PATH (opt-in via env) ──
                if os.environ.get("PEER_PATCHER_ENABLED", "").lower() in ("1", "true", "yes"):
                    from agents.peer_patcher import run_peer_patcher

                    yield sse_event("status", {"message": "Generating via peer patcher..."})

                    current = load_current_artifacts(project.output_dir)
                    digest = registry_digest()
                    registry = registry_snapshot()
                    vocab = token_vocabulary(current)

                    async for evt in run_peer_patcher(
                        user_prompt=description,
                        current_artifacts=current,
                        registry_digest=digest,
                        registry=registry,
                        token_vocabulary=vocab,
                    ):
                        if evt["event"] == "artifacts":
                            commit_artifacts(project.output_dir, evt["data"]["artifacts"])
                            yield sse_event("log",
                                {"text": "[PeerPatcher] Artifacts written to disk"})
                        elif evt["event"] == "error":
                            yield sse_event("log", {"text": evt["data"]["text"]})
                        else:
                            yield sse_event(evt["event"], evt["data"])

                    yield sse_event("office", build_success_event())
                    yield sse_event("agent_result",
                        {"num_turns": 1, "cost_usd": 0, "duration_ms": 0})
                    return
                # ── End peer-patcher path; fall through to relay pipeline ──

                # Sync workflows BEFORE pipeline so they appear even if generation fails
                _sync_workflows_from_plan(project.output_dir, active_plan)

                # Smith invokes the generator (Migration Step 4b) —
                # the pipeline no longer runs autonomously; it's Smith's
                # tool now, bracketed with architect-voice narration.
                from services.smith_agent_adapters import orchestrate_generation
                async for evt in orchestrate_generation(
                    pipeline_fn=run_pipeline,
                    source=PlanSource.text(),
                    output_dir=project.output_dir,
                    plan=active_plan,
                    description=description,
                    project_id=project.id,
                    user_ask=description,
                ):
                    if evt.get("event") == "agent_result":
                        data = json.loads(evt["data"])
                        total_cost += data.get("cost_usd", 0)
                        total_turns += data.get("num_turns", 0)
                        total_duration += data.get("duration_ms", 0)
                    else:
                        yield evt

            # Sync pages from app-model.json → DB
            await _sync_pages_from_app_model(project.id, project.output_dir)
            _generate_schema_from_plan(project.output_dir, req.plan)
            _sync_workflows_from_plan(project.output_dir, req.plan)  # Re-sync in case plan changed

            # Git commit
            commit_msg = (
                f"Figma import: {req.figma_url[:60]}" if is_figma
                else f"{_design_label} import: {_design_req.ref[:60]}" if is_design_import
                else f"Initial generation: {description[:80]}"
            )
            commit_hash = await git_commit(
                project.output_dir,
                commit_msg,
                actor="generator",   # S24-9: an unattributed HEAD cannot be reverted
            )

            # Store results in DB (new session since we're in an async generator)
            from database import async_session
            async with async_session() as session:
                # Create agent job record
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_generator,
                    status=AgentJobStatus.completed,
                    instruction=description,
                    result={
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "duration_ms": total_duration,
                    },
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                session.add(job)
                await session.flush()

                # Create version
                version = Version(
                    project_id=project.id,
                    commit_hash=commit_hash,
                    message=commit_msg,
                    agent_job_id=job.id,
                )
                session.add(version)

                # Store assistant message
                assistant_msg = Conversation(
                    project_id=project.id,
                    role=MessageRole.assistant,
                    content="Application generated successfully.",
                    message_type=MessageType.generation,
                    metadata_={
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "commit_hash": commit_hash,
                    },
                )
                session.add(assistant_msg)

                # Update project status
                from sqlalchemy import update
                await session.execute(
                    update(Project).where(Project.id == project.id).values(
                        status=ProjectStatus.ready,
                    )
                )
                await session.commit()

            # Offer the post-build chat actions (Seed demo data · Validate & Repair)
            # after a full app build, same as the /chat completion path.
            _post_actions = None
            try:
                if commit_hash:
                    from services.post_gen_actions import post_build_actions
                    _post_actions = post_build_actions()
            except Exception:
                _post_actions = None

            # Attach next-steps to the SSE payload too. The DB row with
            # these steps was persisted earlier (see the "What next?" card
            # block ~5750), but the frontend's `complete` handler synthesizes
            # its own assistant message before the DB refetch lands, so
            # without this the chips vanish on-screen even though they're
            # in Postgres. Cheap re-derive — just reads plan.json.
            _next_steps_out = None
            try:
                from services.next_steps import (
                    derive_next_steps_from_output_dir as _dns,
                )
                _ns = _dns(project.output_dir) if project.output_dir else []
                if _ns:
                    _next_steps_out = [s.to_dict() for s in _ns]
            except Exception:
                logger.exception("next_steps derivation for SSE failed")

            yield sse_event("complete", {
                "project_id": str(project.id),
                "num_turns": total_turns,
                "cost_usd": total_cost,
                "duration_ms": total_duration,
                "commit_hash": commit_hash,
                **({"actions": _post_actions} if _post_actions else {}),
                **({"next_steps": _next_steps_out} if _next_steps_out else {}),
            })

            # Self-Verify Pass is USER-INVOKED only. The chip on the
            # generated app opens the "Verify my app" flow; that path
            # runs the diagnose loop, and when it surfaces faults the
            # Smith fix loop auto-repairs (gated by FORGE_VERIFY_SMITH_FIX).
            # We deliberately do NOT auto-trigger on generation completion —
            # verify pulls Playwright + Smith work that should only spend
            # tokens when the user asks for it.

        except Exception as e:
            logger.exception("Generation error in /generate")
            # Update project status to error
            from database import async_session
            async with async_session() as session:
                from sqlalchemy import update
                await session.execute(
                    update(Project).where(Project.id == project.id).values(
                        status=ProjectStatus.error,
                    )
                )
                await session.commit()

            yield sse_event("error", {"message": _unwrap_error(e)})

    return EventSourceResponse(
        buffered_event_stream(event_stream(), str(project_id)),
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/projects/{project_id}/chat")
async def chat_with_project(
    project_id: uuid.UUID,
    req: ChatRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a chat message — classifies intent via orchestrator and routes to specialist agent."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="Project has no output directory")

    # Store user message
    user_msg = Conversation(
        project_id=project.id,
        role=MessageRole.user,
        content=req.message,
        message_type=MessageType.chat,
    )
    db.add(user_msg)

    # Backfill project.description from the first user chat message when the
    # dialog left it blank. The description IS the first prompt the user typed
    # — the dialog's field is redundant with the chat and users routinely skip
    # it, leaving the Projects card showing "No description" for every project
    # created via the chat path. Cap at 500 chars so the card stays scannable.
    if not (project.description or "").strip() and req.message.strip():
        project.description = req.message.strip()[:500]

    await db.commit()

    async def event_stream():
        # Local alias — the Smith-handoff branch below reassigns this to a
        # forwarded ChatRequest, and Python would otherwise treat `req` as
        # local across THIS whole function, breaking every read that runs
        # before the reassignment (UnboundLocalError on [APPROVE_PLAN] etc.).
        req_local = req
        yield sse_event("status", {"message": "Classifying intent..."})

        try:
            # Step 0: Check if project has real code files
            # Exclude Figma prefetch artifacts (reference.png, styles.json, images_manifest.json)
            # and the public/images dir from the "has code" check so that design-analysis-only
            # projects still enter the planning/approval flow.
            _ignore = {
                ".git", ".gitignore", "node_modules", "workflows", "agent-definitions",
                "styles.json", "images_manifest.json", "public", "figma_context",
            }
            # Also ignore reference*.png, package files, and config files
            # that exist before actual code generation
            def _is_prefetch_artifact(f: Path) -> bool:
                name = f.name
                if name.startswith("reference") and name.endswith(".png"):
                    return True
                if name in _ignore:
                    return True
                return False

            project_has_code = False
            if Path(project.output_dir).exists():
                # Check for actual source code (src/ directory with files)
                src_dir = Path(project.output_dir) / "src"
                if src_dir.exists():
                    # Has src/ — but only count if it has files beyond contracts
                    src_files = [f for f in src_dir.rglob("*") if f.is_file() and "contracts" not in str(f)]
                    project_has_code = len(src_files) > 0

            logger.info(f"[chat] project_has_code={project_has_code}, output_dir={project.output_dir}")

            # Load conversation history and check for pending plan + discovery
            conversation_history = await _load_conversation_history(project.id)
            existing_plan, _ = await _load_pending_plan_with_metadata(project.id)
            has_pending_plan = existing_plan is not None and not project_has_code
            pending_dossier = _load_pending_discovery(project.output_dir)
            has_pending_discovery = pending_dossier is not None and not project_has_code

            # Approval signals (discovery-first flow):
            #   [APPROVE_DISCOVERY]  → run planner with the approved dossier
            #   [APPROVE_PLAN]       → dispatch the generation pipeline
            _msg_upper = req_local.message.strip().upper()
            is_discovery_approve = _msg_upper.startswith("[APPROVE_DISCOVERY]")
            is_plan_approve = _msg_upper in ("[APPROVE_PLAN]", "APPROVE_PLAN")
            is_approve_signal = is_discovery_approve or is_plan_approve
            # Fix-Assistant approval chip (detected like [APPROVE_PLAN]).
            is_apply_fix = "[APPLY_FIX]" in _msg_upper

            # Design-template pick — [SELECT_TEMPLATE:<id>]. Record the choice (seeded
            # into design_spec at generation time) and acknowledge; don't run intent.
            import re as _re
            _sel_m = _re.match(r"^\[SELECT_TEMPLATE:([^\]]+)\]$", req_local.message.strip())
            if _sel_m:
                from services.design_template_store import select_by_id
                picked = select_by_id(project.output_dir, _sel_m.group(1).strip())
                if picked:
                    yield sse_event("design_template_selected",
                                    {"id": picked["id"], "name": picked["name"]})
                    yield sse_event("message",
                                    {"text": f"Design set to **{picked['name']}**. Approve the plan when you're ready to build."})
                else:
                    yield sse_event("message", {"text": "That design template is no longer available."})
                yield sse_event("complete", {"project_id": str(project.id)})
                return
            # [APPLY_FIX] — apply a pending Fix-Assistant proposal (has-code only).
            # Short-circuits before intent classification (the chip carries no NL).
            if is_apply_fix and project_has_code:
                async for _ev in _handle_apply_fix(project):
                    yield _ev
                yield sse_event("complete", {"project_id": str(project.id)})
                return

            if is_approve_signal and project_has_code:
                yield sse_event("message", {"text": "Your app has already been generated and is ready! Use the Live Edit or chat to make changes."})
                yield sse_event("complete", {"project_id": str(project.id)})
                return

            # ────────────────────────────────────────────────────────────────
            # Smith-as-architect bootstrap intercept (Phase C).
            # When FORGE_SMITH_ARCHITECT=1 AND we're in bootstrap territory
            # (no code yet AND no discovery/plan already pending intent),
            # route DISCOVERY and PLANNING stages through Smith. Generation
            # ([APPROVE_PLAN]) still falls through to the existing pipeline
            # below — that's the load-bearing build step we don't touch.
            # ────────────────────────────────────────────────────────────────
            from services.smith_chat_v2 import architect_flag_enabled as _arch_on
            _use_architect_bootstrap = (
                _arch_on()
                and not project_has_code
                and not is_plan_approve       # generation stays with pipeline
                and not is_apply_fix          # separately handled above
            )
            _architect_bootstrap_ran = False
            if _use_architect_bootstrap:
                # SPEED (Task 3): persist the Fast/Complete pick HERE. The
                # smith-arch bootstrap path is the one that actually runs, but it
                # never saved the profile — only the classic branch below did,
                # which this intercept bypasses. So generation-profile.json never
                # existed, orchestrate_planner's load_profile() returned None, and
                # a "fast" build planned exactly like "complete" (revise re-stream
                # and all). Save it before planning so the profile is honoured.
                if is_discovery_approve:
                    try:
                        from services.generation_profile import (
                            get_profile, persist_profile,
                        )
                        _picked = _parse_generation_profile_id(req_local.message)
                        _profile = get_profile(_picked)
                        persist_profile(project.output_dir, _profile)
                        yield sse_event("generation_profile_selected", {
                            "id": _profile.id, "label": _profile.label,
                            "eta_minutes": _profile.eta_minutes,
                        })
                        logger.info("[smith-arch] persisted profile=%s", _profile.id)
                    except Exception:  # noqa: BLE001 — never block on this
                        logger.exception("[smith-arch] persist profile failed")
                from services.smith_architect_wire import run_bootstrap_stage
                # Bridge: run_bootstrap_stage → orchestrate_planner emit_fn
                # → asyncio.Queue → SSE stream. Lets the Actor-Critic loop
                # push critic_start/critic_verdict/critic_approved/… as
                # SSE events while planning is still running, so the user
                # sees the loop live instead of a black-box wait.
                _critic_q: asyncio.Queue = asyncio.Queue()
                def _bootstrap_emit(stage: str, payload: dict) -> None:
                    try:
                        _critic_q.put_nowait({"stage": stage, "payload": payload})
                    except Exception:  # noqa: BLE001 — queue closed / full
                        logger.exception(
                            "[smith-arch] bootstrap emit_fn put failed"
                        )
                _stage_task = asyncio.create_task(run_bootstrap_stage(
                    project_id=str(project.id),
                    output_dir=project.output_dir,
                    user_message=req_local.message,
                    is_discovery_approve=is_discovery_approve,
                    is_plan_approve=False,
                    pending_dossier=pending_dossier,
                    emit_fn=_bootstrap_emit,
                ))
                # Drain the queue in parallel with the bootstrap task —
                # yield each event as SSE immediately, then keep polling
                # every 250ms until the task is done. On completion,
                # flush any remaining events before consuming the result.
                # ── Planning progress (Task 4): authoritative, honest, bounded ──
                # The main pipeline emits only `status` strings (zero `progress`
                # events), so the ring falls back to frontend interpolation whose
                # scale factor BALLOONS the ETA once planning overruns its 180s
                # baseline — reproduced live as "18%, ~18 min, label stuck on
                # 'Classifying intent'". For the BUILD path (discovery-approve) we
                # now emit real `progress` events with a profile-anchored ETA, a
                # bounded percent, and the correct phase label. Plain Smith Q&A
                # (not a build) stays on the light heartbeat — it's a quick turn.
                _plan_prog = None
                _plan_started = time.monotonic()
                if is_discovery_approve:
                    try:
                        from services.generation_profile import get_profile as _gp
                        _pp = _gp(_parse_generation_profile_id(req_local.message))
                        _total_eta_s = max(60, int(_pp.eta_minutes) * 60)
                    except Exception:  # noqa: BLE001
                        _total_eta_s = 720
                    _plan_prog = {
                        "total_eta_s": _total_eta_s,
                        # Planning can't credibly claim less time than the build
                        # still needs — floor the ETA at ~half the run so it
                        # plateaus instead of counting down to "almost done"
                        # while the plan is still streaming.
                        "build_floor_s": int(_total_eta_s * 0.5),
                    }
                    yield sse_event("status", {"message": "Planning your app…"})

                _stage_result = None
                _hb_ticks = 0
                try:
                    while not _stage_task.done():
                        try:
                            _e = await asyncio.wait_for(
                                _critic_q.get(), timeout=0.25,
                            )
                            yield sse_event(_e["stage"], _e["payload"])
                        except asyncio.TimeoutError:
                            # SSE HEARTBEAT (reliability): the planning stage
                            # streams a big plan for MINUTES without putting
                            # anything on the queue, so this loop would yield zero
                            # bytes the whole time. A silent streaming response
                            # gets dropped by the client/proxy → the UI reverts to
                            # the "Choose how to build" step while the backend is
                            # still building ("never builds"; reproduced live).
                            # Emitting progress/heartbeat every ~1-3s keeps the
                            # connection alive AND drives an honest live ring.
                            _hb_ticks += 1
                            if _plan_prog is not None:
                                # Authoritative planning progress — replaces the
                                # ballooning frontend guess with honest numbers.
                                _elapsed = time.monotonic() - _plan_started
                                # Bounded asymptotic climb 2%→~18%: always rising
                                # (never freezes) yet capped (never overstates —
                                # planning is only the run's opening slice).
                                _pct = 2.0 + 16.0 * (_elapsed / (_elapsed + 150.0))
                                _eta = max(
                                    _plan_prog["build_floor_s"],
                                    _plan_prog["total_eta_s"] - _elapsed,
                                )
                                if _hb_ticks % 4 == 0:  # ~1 Hz
                                    yield sse_event("progress", {
                                        "phase": "Planning your app",
                                        "phase_index": -1,
                                        "phase_total": 0,
                                        "phase_percent": round(_pct, 1),
                                        "overall_percent": round(_pct, 1),
                                        "eta_seconds": int(_eta),
                                        "sub_label": "Designing schema, pages & flows",
                                    })
                            elif _hb_ticks % 12 == 0:
                                yield sse_event("heartbeat", {
                                    "stage": "planning",
                                    "elapsed_s": _hb_ticks // 4,
                                })
                            continue
                    while not _critic_q.empty():
                        _e = _critic_q.get_nowait()
                        yield sse_event(_e["stage"], _e["payload"])
                    _stage_result = _stage_task.result()
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[smith-arch] bootstrap stage crashed — falling back"
                    )
                    _stage_result = None

                if _stage_result is not None and _stage_result.stage in ("discovery", "planning"):
                    _architect_bootstrap_ran = True
                    logger.info(
                        "[smith-arch] bootstrap stage=%s narrator=%s",
                        _stage_result.stage, (_stage_result.narrator or "")[:120],
                    )
                    if _stage_result.stage == "discovery":
                        # Persist dossier + emit existing SSE shapes so the
                        # frontend's DiscoveryCard still renders (spec §5.1
                        # loop 3: user approves or suggests changes).
                        _save_pending_discovery(project.output_dir, _stage_result.dossier)
                        await _persist_assistant_message(
                            project.id,
                            _stage_result.narrator or "I researched your domain.",
                            MessageType.chat,
                            metadata={"discovery": _stage_result.dossier,
                                      "intent": "DISCOVERY",
                                      "smith_arch": True},
                        )
                        yield sse_event("discovery_complete", _stage_result.dossier)
                        yield sse_event("discovery_approval_needed", {
                            "editable_fields": sorted(_DISCOVERY_EDITABLE_KEYS),
                            "signal": "[APPROVE_DISCOVERY]",
                            "instruction": (
                                "Review the dossier. Send `[APPROVE_DISCOVERY]` "
                                "to continue to planning, or `[APPROVE_DISCOVERY] "
                                "{\"domain\": \"…\"}` with edits."
                            ),
                        })
                        yield sse_event("complete", {
                            "project_id": str(project.id), "intent": "DISCOVERY",
                        })
                        return
                    if _stage_result.stage == "planning":
                        # Plan emitted → PlanCard flow. Fall through to the
                        # existing plan_ready + persistence pattern.
                        await _persist_assistant_message(
                            project.id,
                            _stage_result.narrator or "Plan drafted.",
                            MessageType.plan,
                            metadata={"plan": _stage_result.plan,
                                      "intent": "PLAN",
                                      "smith_arch": True},
                        )
                        yield sse_event("plan_ready", {"plan": _stage_result.plan})
                        _bp_record_plan(project, _stage_result.plan)
                        yield sse_event("complete", {
                            "project_id": str(project.id), "intent": "PLAN",
                        })
                        return
                # stage="not_enabled" (error) or "generation" (hand-off) →
                # fall through to the existing pipeline below.
                if _stage_result and _stage_result.stage == "not_enabled" and _stage_result.error:
                    logger.info(
                        "[smith-arch] bootstrap error — falling back to tactical: %s",
                        _stage_result.error,
                    )

            # Route [APPROVE_DISCOVERY] into its own branch — it runs the
            # planner. Different intent string so the planning-branch
            # dispatcher below doesn't try to dispatch the pipeline.
            if is_discovery_approve and has_pending_discovery:
                intent = "APPROVE_DISCOVERY"
                classification = {"intent": "APPROVE_DISCOVERY"}
                logger.info(f"[chat] Detected discovery-approval signal — running planner")
            elif is_plan_approve and has_pending_plan:
                intent = "APPROVE"
                classification = {"intent": "APPROVE"}
                logger.info(f"[chat] Detected plan-approval signal — dispatching pipeline")
            elif (
                _smith_enabled()
                and not has_pending_plan
                and not has_pending_discovery
            ):
                # AGENTIC ROUTER: Smith is the single entry point for any
                # free-form message when the flag is on. He decides — via
                # his tool palette — whether the turn is a greeting, a
                # build description, a fix symptom, an explain question,
                # or a continuation of a prior partial-apply. If he needs
                # the platform's discovery/planner/refiner, he calls
                # handoff_to_pipeline(kind, message); we translate that
                # signal into a redispatch through the pipeline branches
                # below.
                logger.info(f"[chat] Smith agentic intercept — routing free-form turn through _handle_smith_turn")
                deferred_signal: dict = {}
                async for _ev in _handle_smith_turn(project, req_local.message, deferred_signal, current_route=getattr(req_local, "current_route", None), attachment_ids=getattr(req_local, "attachment_ids", None)):
                    yield _ev
                if not deferred_signal.get("handoff"):
                    # Smith terminated with answer / propose_fix / ask_user —
                    # nothing more to do this turn.
                    yield sse_event("complete", {"project_id": str(project.id), "intent": "SMITH"})
                    return
                # Smith requested handoff. Rewrite the classification so
                # the existing pipeline branches below run against Smith's
                # forwarded message + a synthesized intent that matches
                # what the pipeline expects.
                hnd = deferred_signal["handoff"]
                req_local = _make_forwarded_request(req_local, hnd["message"])
                _HANDOFF_INTENT = {"discovery": "DISCOVER",
                                   "planner": "PLAN",
                                   "refine": "REFINE"}
                intent = _HANDOFF_INTENT.get(hnd["kind"], "REFINE")
                classification = {"intent": intent, "reasoning": f"Smith handoff → {hnd['kind']}"}
                logger.info(f"[chat] Smith handoff → pipeline kind={hnd['kind']} intent={intent}")
                # Fall through to the existing pipeline dispatcher below.
            else:
                # Step 1: Classify intent (with conversation context)
                from agents.orchestrator import classify_intent
                classification = await classify_intent(
                    req_local.message,
                    project.output_dir,
                    conversation_history=conversation_history,
                    has_pending_plan=has_pending_plan,
                )
                intent = classification.get("intent", "REFINE")
                # Normalize: LLM sometimes returns "APPROVE_PLAN" for [APPROVE_PLAN] messages
                if intent in ("APPROVE_PLAN", "APPROVE_PLAN]"):
                    intent = "APPROVE"
            logger.info(f"[chat] classified intent={intent}, classification={classification}")

            # Treat APPROVE intent as pending approval — BUT only if a plan is already saved.
            # If no plan exists yet, fall through to the planner so it can produce plan-json.
            # (Handles: user clicks "Use smart defaults" after a text-only plan summary that
            #  had no plan-json block — the planner re-runs and this time outputs proper JSON.)
            has_pending_approval = not project_has_code and intent == "APPROVE" and has_pending_plan

            # Fallback: if a plan exists and the LLM classified as PLAN/SCAFFOLD/DISCOVER,
            # the user likely wants to proceed with the existing plan
            if not has_pending_approval and has_pending_plan and intent in ("PLAN", "SCAFFOLD", "DISCOVER"):
                logger.info(f"[chat] Plan exists and user sent {intent}-classified message — treating as approval")
                has_pending_approval = True

            # When APPROVE intent but no plan saved, treat as PLAN so planner runs again
            if intent == "APPROVE" and not has_pending_plan:
                logger.info(f"[chat] APPROVE intent but no saved plan — re-routing to planner to produce plan-json")
                intent = "PLAN"

            logger.info(f"[chat] has_pending_approval={has_pending_approval}, entering planning branch={not project_has_code and (intent in ('PLAN', 'SCAFFOLD', 'DISCOVER', 'APPROVE', 'APPROVE_DISCOVERY') or has_pending_approval)}")
            if not project_has_code and (intent in ("PLAN", "SCAFFOLD", "DISCOVER", "APPROVE", "APPROVE_DISCOVERY") or has_pending_approval):
                # ── Discovery-approval branch ──────────────────────────────
                # User sent [APPROVE_DISCOVERY]. Apply any edits, persist the
                # final dossier to src/contracts/discovery.json, then run
                # the planner WITH the dossier as domain_context so the
                # planner produces entity/workflow/page choices informed by
                # the researched domain knowledge. No pipeline dispatch yet
                # — emits plan_ready and pauses for [APPROVE_PLAN].
                if intent == "APPROVE_DISCOVERY":
                    logger.info(f"[chat] Processing discovery approval for project {project.id}")
                    if not pending_dossier:
                        yield sse_event("message", {"text": "No discovery dossier found to approve. Please regenerate from your description."})
                        yield sse_event("complete", {"project_id": str(project.id)})
                        return

                    edits = _parse_discovery_edits(req_local.message)
                    approved_discovery = _apply_discovery_edits(pending_dossier, edits)
                    if edits:
                        yield sse_event("log", {
                            "text": f"[Discovery] User edits applied: {sorted(edits.keys())}",
                        })
                    # GP-1: persist the generation-profile choice (Fast vs
                    # Complete). Downstream phases read the profile via
                    # services.generation_profile.load_profile(output_dir);
                    # a missing pick means the caller falls back to Fast.
                    try:
                        from services.generation_profile import (
                            get_profile, persist_profile,
                        )
                        _picked = _parse_generation_profile_id(req_local.message)
                        _profile = get_profile(_picked)
                        persist_profile(project.output_dir, _profile)
                        yield sse_event("generation_profile_selected", {
                            "id": _profile.id,
                            "label": _profile.label,
                            "eta_minutes": _profile.eta_minutes,
                        })
                    except Exception:  # noqa: BLE001
                        logger.exception("[GP-1] persist profile failed")
                    # Persist final dossier to the canonical contract path
                    # so [APPROVE_PLAN] below can reload it cheaply when
                    # dispatching the pipeline.
                    from agents.domain_agent import persist_discovery
                    persist_discovery(project.output_dir, approved_discovery)
                    _clear_pending_discovery(project.output_dir)
                    yield sse_event("discovery_approved", {
                        "domain": approved_discovery.get("domain"),
                        "complianceNotes": approved_discovery.get("complianceNotes"),
                    })

                    # Run planner with the approved dossier
                    yield sse_event("intent", {"intent": "PLAN", "reasoning": "Domain approved — drafting plan"})
                    yield sse_event("status", {"message": "Drafting your application plan..."})
                    # Planner on the Anthropic SDK (same reliable transport as discovery,
                    # ~90s) instead of the bundled CLI, which wedges/crawls for 30-40 min.
                    # Returns a fully-sanitized plan dict (_annotate_page_types applies the
                    # page-type, entity-infer, action + design sanitizers).
                    # produce_plan() keeps the one-shot path byte-unchanged for
                    # small/medium apps and routes large apps through the
                    # skeleton→per-unit decomposition (with one-shot fallback).
                    plan = None
                    # JT-T4: pull the discovery-time StructuredBrief so the
                    # planner honors actors + journeys captured in the
                    # AUTHORITATIVE INPUTS block. Legacy projects (no session
                    # with a structured brief) get None → planner falls
                    # through to normal authoring, byte-unchanged.
                    _brief_for_planner = None
                    try:
                        from services.brief_lookup import get_structured_brief_for_project
                        _brief_for_planner = await get_structured_brief_for_project(
                            db, project.id,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("[planner] structured-brief lookup failed")
                    _fail_text = ""
                    try:
                        async for _pkind, _ppayload in _stream_produce_plan(
                            approved_discovery.get("description") or req_local.message,
                            project.output_dir,
                            domain_context=approved_discovery,
                            structured_brief=_brief_for_planner,
                        ):
                            if _pkind == "event":
                                yield _ppayload
                            else:
                                plan = _ppayload
                    except Exception as _pe:
                        logger.exception("[chat] planner (SDK) failed")
                        yield sse_event("log", {"text": f"[Planner] failed: {_pe}"})
                        # Visible failure — a bare `log` event leaves the chat
                        # silent (an empty assistant message was all the user
                        # saw when planning timed out). Say what happened and
                        # that re-approving retries from the saved dossier.
                        _fail_text = (
                            "Planning didn't finish — the plan stream was "
                            "interrupted before completion. Your research "
                            "dossier is saved; approve it again to retry."
                        )
                        yield sse_event("message", {"text": _fail_text})
                    full_text = json.dumps(plan, indent=2) if plan else _fail_text
                    if plan:
                        from agents.planner import classify_register_llm
                        brief = approved_discovery.get("description") or req_local.message
                        plan["register"] = await classify_register_llm(
                            brief, plan.get("domain", ""), plan
                        )

                    metadata: dict = {"intent": "PLAN"}
                    if plan:
                        metadata["plan"] = plan
                        # Templates BEFORE plan_ready — see the note at the other
                        # call sites: keeps Begin Quest enabled the instant it
                        # appears (kills the multi-click dead-window).
                        async for _tev in _offer_design_templates(plan, project.output_dir):
                            yield _tev
                        yield sse_event("plan_ready", {"plan": plan})
                        _bp_record_plan(project, plan)

                    await _persist_assistant_message(
                        project.id,
                        full_text,
                        MessageType.plan if plan else MessageType.chat,
                        metadata=metadata,
                    )
                    yield sse_event("complete", {"project_id": str(project.id), "intent": "PLAN"})
                    return

                # Check if this is a plan approval message
                is_approval = has_pending_approval

                if is_approval:
                    logger.info(f"[chat] Processing plan approval for project {project.id}")
                    # Load the approved plan and its full metadata
                    plan, plan_metadata = await _load_pending_plan_with_metadata(project.id)
                    if not plan:
                        logger.warning(f"[chat] No plan found for approval, project {project.id}")
                        yield sse_event("message", {"text": "No plan found to approve. Let me help you create one."})
                        yield sse_event("complete", {"project_id": str(project.id)})
                        return

                    # Snapshot the *generation dossier* (original intent + the
                    # finalized plan) to contracts/generation-dossier.json so a
                    # later fix-chat can recall WHY this app is the way it is
                    # without hitting Postgres. Best-effort — never fails a build.
                    try:
                        from services.app_recall import emit_generation_dossier
                        emit_generation_dossier(
                            project.output_dir,
                            plan,
                            prompt=(plan_metadata or {}).get("original_prompt")
                            or plan.get("description"),
                        )
                    except Exception as _dossier_ex:
                        logger.warning(f"[chat] generation-dossier snapshot skipped: {_dossier_ex}")

                    # Load the previously approved dossier from disk (written
                    # by the [APPROVE_DISCOVERY] branch above). If missing —
                    # e.g. a legacy project from before the discovery-first
                    # flow — set approved_discovery=None so the pipeline
                    # runs its own inline discovery.
                    approved_discovery = None
                    discovery_path = Path(project.output_dir) / "src" / "contracts" / "discovery.json"
                    if discovery_path.exists():
                        try:
                            approved_discovery = json.loads(discovery_path.read_text())
                        except Exception:
                            logger.warning(f"[chat] discovery.json present but unreadable; pipeline will re-run discovery")

                    # Detect Figma project: check metadata for figma_url or check for reference.png
                    is_figma_project = bool(
                        (plan_metadata and plan_metadata.get("figma_url"))
                        or (Path(project.output_dir) / "reference.png").exists()
                    )
                    # A design imported through a provider adapter (UX Pilot):
                    # the plan metadata carries provider + ref + credential row.
                    _design_meta = (plan_metadata or {}).get("design") if plan_metadata else None
                    is_design_project = bool(
                        isinstance(_design_meta, dict)
                        and _design_meta.get("provider")
                        and _design_meta.get("provider") != "figma"
                    )
                    if is_design_project:
                        is_figma_project = False

                    yield sse_event("intent", {"intent": "GENERATE", "reasoning": "Plan approved — generating code"})
                    yield sse_event("status", {"message": "Generating application code..."})

                    # Sync workflows early so they appear even if generation fails
                    _sync_workflows_from_plan(project.output_dir, plan)

                    # The design pipeline's context signal. plan rarely has a
                    # description, and req_local.message here is the user's
                    # APPROVAL message ("yes build it") — worthless as design
                    # signal. The ORIGINAL prompt is the richest text we have.
                    description = ((plan_metadata or {}).get("original_prompt")
                                   or plan.get("description")
                                   or req_local.message)
                    total_cost = 0
                    total_turns = 0
                    total_duration = 0

                    # Pipeline branch: Figma-driven plans flow through the dedicated
                    # _run_figma_relay_pipeline (which fires our Phase 1-3 work — the
                    # deterministic Figma mapper writes page schemas without the LLM
                    # schema agent). Non-Figma plans use the description pipeline.
                    figma_url = plan_metadata.get("figma_url", "").strip() if plan_metadata else ""
                    figma_token = ""
                    if is_figma_project and figma_url:
                        from services.design_import import figma_token_for as _figma_token_for
                        from database import async_session as _async_session
                        async with _async_session() as _fsess:
                            figma_token, _figma_row_id = await _figma_token_for(
                                (plan_metadata or {}).get("design"),
                                db=_fsess, org_id=project.org_id,
                                legacy_token=(plan_metadata or {}).get("figma_token"),
                            )
                        if not figma_token:
                            yield sse_event("log", {"text": (
                                "[Figma] no Figma access: register Figma under Settings → MCP Servers "
                                "— building from the plan without the design"
                            )})

                    if is_figma_project and figma_url and figma_token:
                        # Ensure plan.pages came from the Figma file. The /chat
                        # plan-approval flow can present an LLM-generated plan
                        # to the user even for a Figma project — rebuild it
                        # from Figma so plan.pages match the actual frames.
                        if not plan.get("_figma_driven"):
                            try:
                                from services.figma_plan_builder import build_plan_from_figma
                                figma_plan = await build_plan_from_figma(figma_url, figma_token)
                                try:
                                    from services.figma_plan_binding import (
                                        enrich_figma_plan_with_bindings, make_anthropic_call_llm,
                                    )
                                    from services.figma_client import fetch_figma_file
                                    from figma_parser import parse_figma_url as _parse
                                    _fk = _parse(figma_url)["file_key"]
                                    _meta = await fetch_figma_file(_fk, figma_token, depth=3)
                                    figma_plan = await enrich_figma_plan_with_bindings(
                                        figma_plan, _meta, call_llm=make_anthropic_call_llm())
                                except Exception as _enr_ex:
                                    logger.warning("[chat] binding enrichment skipped: %s", _enr_ex)
                                # Preserve the original plan's description / non-pages fields,
                                # but let Figma own pages + the marker.
                                plan = {
                                    **plan,
                                    "pages": figma_plan["pages"],
                                    "figma_file_key": figma_plan["figma_file_key"],
                                    "figma_url": figma_plan["figma_url"],
                                    # Carry binding intent so the binding pass can read it.
                                    "data_models": figma_plan.get("data_models", []),
                                    "workflows": figma_plan.get("workflows", []),
                                    "_figma_driven": True,
                                }
                                logger.info(
                                    f"[chat] Figma plan rebuilt with {len(figma_plan['pages'])} page(s): "
                                    f"{[p['route'] for p in figma_plan['pages']]}"
                                )
                            except Exception as _fp_ex:
                                logger.warning(
                                    f"[chat] build_plan_from_figma failed: {_fp_ex} — "
                                    f"falling back to description pipeline"
                                )
                                # Fall through to the description path below
                                is_figma_project = False

                    if is_design_project or (is_figma_project and figma_url and figma_token):
                        # Fix 4 — branding lock. When a design is the source, the
                        # user's project name is authoritative for `appName`:
                        # the planner/LLM would otherwise infer a name from the
                        # description ("Product Image Scraper App") or pick a
                        # generic brand ("LensShop"), overwriting what the user
                        # deliberately typed ("Snap2App"). Only lock when the
                        # project name is real (not the "New Project" default
                        # or an empty string). `_resolve_app_name` treats the
                        # domain slug as "generic" and would replace it with a
                        # design-DNA brand — stamping appName here beats that
                        # branch too.
                        _proj_name = (getattr(project, "name", "") or "").strip()
                        if _proj_name and _proj_name.lower() not in {"", "new project", "untitled", "app"}:
                            plan["appName"] = _proj_name
                            plan["name"] = _proj_name  # sibling used by some readers
                            logger.info("[figma] branding lock: appName=%r (from project.name)", _proj_name)
                        if is_design_project:
                            from services.design_import import plan_source_from_metadata
                            from database import async_session as _async_session
                            async with _async_session() as _dsess:
                                _design_source = await plan_source_from_metadata(
                                    _design_meta, db=_dsess, org_id=project.org_id,
                                )
                            logger.info("[chat] %s project approval — Smith invokes design generator",
                                        _design_meta.get("provider"))
                        else:
                            _design_source = PlanSource.figma(
                                url=figma_url, token=figma_token,
                                credential_id=((plan_metadata or {}).get("design") or {}).get("credential_id"),
                            )
                            logger.info("[chat] Figma project approval — Smith invokes figma generator")
                        from services.smith_agent_adapters import orchestrate_generation
                        async for evt in orchestrate_generation(
                            pipeline_fn=run_pipeline,
                            source=_design_source,
                            output_dir=project.output_dir,
                            plan=plan,
                            description=description,
                            domain_context=approved_discovery,
                            project_id=project.id,
                            user_ask=description,
                        ):
                            if evt.get("event") == "agent_result":
                                data = json.loads(evt["data"])
                                total_cost += data.get("cost_usd", 0)
                                total_turns += data.get("num_turns", 0)
                                total_duration += data.get("duration_ms", 0)
                            else:
                                yield evt
                    else:
                        logger.info("[chat] Text project approval — Smith invokes generator")
                        from services.smith_agent_adapters import orchestrate_generation
                        async for evt in orchestrate_generation(
                            pipeline_fn=run_pipeline,
                            source=PlanSource.text(),
                            output_dir=project.output_dir,
                            plan=plan,
                            description=description,
                            project_id=project.id,
                            domain_context=approved_discovery,
                            user_ask=description,
                        ):
                            if evt.get("event") == "agent_result":
                                data = json.loads(evt["data"])
                                total_cost += data.get("cost_usd", 0)
                                total_turns += data.get("num_turns", 0)
                                total_duration += data.get("duration_ms", 0)
                            else:
                                yield evt

                    await _sync_pages_from_app_model(project.id, project.output_dir)
                    _generate_schema_from_plan(project.output_dir, plan)
                    _sync_workflows_from_plan(project.output_dir, plan)
                    commit_msg = (
                        f"Figma import: {plan_metadata.get('figma_url', '')[:60]}"
                        if is_figma_project
                        else f"{_design_meta.get('provider')} import: {str(_design_meta.get('ref', ''))[:60]}"
                        if is_design_project
                        else f"Initial generation: {description[:80]}"
                    )
                    commit_hash = await git_commit(project.output_dir, commit_msg,
                                                   actor="generator")   # S24-9

                    # Persist results
                    from database import async_session
                    async with async_session() as sess:
                        job = AgentJob(
                            project_id=project.id,
                            agent_type=AgentType.code_generator,
                            status=AgentJobStatus.completed,
                            instruction=description,
                            result={"num_turns": total_turns, "cost_usd": total_cost, "duration_ms": total_duration},
                            started_at=datetime.now(timezone.utc),
                            completed_at=datetime.now(timezone.utc),
                        )
                        sess.add(job)
                        await sess.flush()
                        if commit_hash:
                            sess.add(Version(project_id=project.id, commit_hash=commit_hash,
                                             message=commit_msg, agent_job_id=job.id))
                        sess.add(Conversation(
                            project_id=project.id, role=MessageRole.assistant,
                            content="Application generated successfully.",
                            message_type=MessageType.generation,
                            metadata_={"num_turns": total_turns, "cost_usd": total_cost, "commit_hash": commit_hash},
                        ))

                        # "What next?" card — derived from plan.json so
                        # every chip names a real entity / route. This
                        # is Smith's first message after generation and
                        # keeps the user from staring at a fresh app
                        # with no idea what to do next.
                        try:
                            from services.next_steps import (
                                derive_next_steps_from_output_dir,
                            )
                            _next_steps = derive_next_steps_from_output_dir(
                                project.output_dir,
                            )
                        except Exception:
                            logger.exception("next_steps derivation failed")
                            _next_steps = []
                        if _next_steps:
                            sess.add(Conversation(
                                project_id=project.id,
                                role=MessageRole.assistant,
                                content=(
                                    "Your app is ready. Here's what you can "
                                    "try next — or just tell me what you'd "
                                    "like to change."
                                ),
                                message_type=MessageType.chat,
                                metadata_={
                                    "next_steps": [s.to_dict() for s in _next_steps],
                                },
                            ))

                        # Update project status to ready
                        from sqlalchemy import update
                        await sess.execute(
                            update(Project).where(Project.id == project.id).values(
                                status=ProjectStatus.ready,
                            )
                        )
                        await sess.commit()

                    # Post-build chips (Seed demo data · Validate & Repair) — this is
                    # the [APPROVE_PLAN] build completion, the path a real generation
                    # takes, so the actions must ride THIS complete event.
                    _post_actions = None
                    try:
                        if commit_hash:
                            from services.post_gen_actions import post_build_actions
                            _post_actions = post_build_actions()
                    except Exception:
                        _post_actions = None

                    # Blueprint change_log hook (spec §6.3) — one entry per
                    # generation run naming the file set (from git — no
                    # self-report) + tying to the user ask.
                    _bp_files: list[str] = []
                    if commit_hash:
                        try:
                            import subprocess as _sp
                            _out = _sp.check_output(
                                ["git", "-C", project.output_dir, "diff-tree",
                                 "--no-commit-id", "--name-only", "-r", commit_hash],
                                text=True, timeout=10,
                            )
                            _bp_files = [ln for ln in _out.splitlines() if ln.strip()]
                        except Exception:  # noqa: BLE001
                            _bp_files = []
                    _bp_record_generation_complete(project, _bp_files, req_local.message)

                    yield sse_event("complete", {
                        "project_id": str(project.id),
                        "num_turns": total_turns, "cost_usd": total_cost,
                        "duration_ms": total_duration, "commit_hash": commit_hash,
                        **({"actions": _post_actions} if _post_actions else {}),
                    })
                    return

                # Not an approval — run planning/analysis conversation
                # Detect Figma project: if reference.png exists, re-run design analyzer
                is_figma_adjust = (Path(project.output_dir) / "reference.png").exists()

                if is_figma_adjust:
                    # Figma project: re-run design analyzer with user feedback
                    yield sse_event("intent", {"intent": "DESIGN_ANALYSIS", "reasoning": "Adjusting design requirements"})
                    yield sse_event("status", {"message": "Re-analyzing design with your feedback..."})

                    # Load previous metadata to get figma_url; the token is
                    # resolved from the org's Figma row, never read back.
                    _, prev_metadata = await _load_pending_plan_with_metadata(project.id)
                    figma_url = prev_metadata.get("figma_url", "") if prev_metadata else ""
                    _prev_design = (prev_metadata or {}).get("design") or {}
                    from services.design_import import figma_token_for as _figma_token_for
                    from database import async_session as _async_session
                    async with _async_session() as _fsess:
                        figma_token, _figma_row_id = await _figma_token_for(
                            _prev_design, db=_fsess, org_id=project.org_id,
                            legacy_token=(prev_metadata or {}).get("figma_token"),
                        )

                    # Detect Figma URL update in user message
                    import re as _re
                    _figma_url_match = _re.search(
                        r'https?://(?:www\.)?figma\.com/(?:file|design)/[A-Za-z0-9]+',
                        req_local.message,
                    )
                    if _figma_url_match:
                        new_figma_url = _figma_url_match.group(0)
                        from services.figma_context import should_refetch_figma
                        if should_refetch_figma(project.output_dir, new_figma_url):
                            logger.info("[chat] New Figma URL detected — re-fetching design data")
                            yield sse_event("status", {"message": "New Figma URL detected — re-fetching design..."})
                            from agent import _prefetch_figma_data
                            parsed = parse_figma_url(new_figma_url)
                            await _prefetch_figma_data(
                                file_key=parsed["file_key"],
                                node_id=parsed.get("node_id"),
                                output_dir=project.output_dir,
                                figma_token=figma_token,
                            )
                            from services.figma_context import extract_figma_context
                            extract_figma_context(project.output_dir, new_figma_url)
                            figma_url = new_figma_url

                    from agents.design_analyzer import run_design_analyzer
                    collected_text: list[str] = []

                    # Load conversation history so the analyzer sees user adjustments
                    conversation_history = await _load_conversation_history(project.id)

                    async for evt in stream_agent_messages(
                        run_design_analyzer(
                            output_dir=project.output_dir,
                            figma_url=figma_url,
                            conversation_history=conversation_history,
                        ),
                        output_dir=project.output_dir,
                        as_messages=True,
                    ):
                        if evt.get("event") == "message":
                            data = json.loads(evt["data"]) if isinstance(evt.get("data"), str) else evt.get("data", {})
                            collected_text.append(data.get("text", ""))
                        if evt.get("event") == "agent_result":
                            pass
                        else:
                            yield evt

                    full_text = "\n".join(collected_text)
                    plan = _extract_plan_json(full_text)

                    metadata: dict = {
                        "intent": "DESIGN_ANALYSIS",
                        "figma_url": figma_url,
                        "design": {
                            "provider": "figma",
                            "ref": figma_url,
                            "credential_id": _prev_design.get("credential_id") or _figma_row_id,
                        },
                    }
                    if plan:
                        metadata["plan"] = plan
                        # Templates BEFORE plan_ready — see the note at the other
                        # call sites: keeps Begin Quest enabled the instant it
                        # appears (kills the multi-click dead-window).
                        async for _tev in _offer_design_templates(plan, project.output_dir):
                            yield _tev
                        yield sse_event("plan_ready", {"plan": plan})
                        _bp_record_plan(project, plan)

                    await _persist_assistant_message(
                        project.id,
                        full_text,
                        MessageType.plan if plan else MessageType.chat,
                        metadata=metadata,
                    )

                    yield sse_event("complete", {"project_id": str(project.id), "intent": "DESIGN_ANALYSIS"})
                    return

                # Text-based project: run planning conversation.
                #
                # DISCOVERY-1: when the user's first substantive turn on a
                # fresh project is DISCOVER (Smith's kind=discovery handoff)
                # AND we have no existing dossier/plan yet, run the real
                # discovery agent, present the dossier, and pause for
                # [APPROVE_DISCOVERY]. The APPROVE_DISCOVERY branch above
                # already runs the planner with the approved dossier as
                # domain_context, so this closes the loop.
                #
                # Legacy fast-path preserved: if the user typed PLAN or
                # already has a pending dossier, fall through to the
                # detect_domain shortcut below — no regression on second
                # turns, on APPROVE loops, or on projects that already
                # carry a discovery.json.
                _existing_discovery = (
                    pending_dossier is not None
                    or (Path(project.output_dir) / "src" / "contracts" / "discovery.json").exists()
                )
                if intent == "DISCOVER" and not _existing_discovery and not has_pending_plan:
                    logger.info(f"[chat] DISCOVER intent — running domain discovery agent (project {project.id})")
                    yield sse_event("intent", {
                        "intent": "DISCOVERY",
                        "reasoning": "Researching your domain before drafting a plan",
                    })
                    yield sse_event("status", {"message": "Researching domain context..."})
                    yield sse_event("discovery_started", {"description": req_local.message[:200]})

                    try:
                        from agents.domain_agent import run_domain_discovery
                        dossier = await run_domain_discovery(
                            req_local.message, plan=None, enable_web_search=True,
                        )
                    except Exception as _dx:
                        logger.exception("[chat] discovery agent failed: %s", _dx)
                        yield sse_event("log", {
                            "text": f"[Discovery] ⚠ FAILED: {_dx} — falling back to fast path",
                        })
                        # Fall through to the detect_domain shortcut below
                        # so the user still gets a plan on discovery failure.
                        dossier = None

                    if dossier:
                        _save_pending_discovery(project.output_dir, dossier)
                        # Blueprint hook (parallel to /generate flow).
                        try:
                            from services.blueprint_pipeline_hooks import record_discovery as _record_discovery
                            _bp_dossier = dict(dossier) if isinstance(dossier, dict) else {}
                            _bp_dossier.setdefault("user_prompt", req_local.message)
                            _record_discovery(
                                output_dir=project.output_dir,
                                project_id=str(project.id),
                                dossier=_bp_dossier,
                            )
                        except Exception:  # noqa: BLE001
                            logger.exception("[blueprint] discovery hook (chat) failed")

                        await _persist_assistant_message(
                            project.id,
                            "I researched your domain. Review the dossier and "
                            "tweak anything before I draft the plan.",
                            MessageType.chat,
                            metadata={"discovery": dossier, "intent": "DISCOVERY"},
                        )
                        yield sse_event("discovery_complete", dossier)
                        yield sse_event("discovery_approval_needed", {
                            "editable_fields": sorted(_DISCOVERY_EDITABLE_KEYS),
                            "signal": "[APPROVE_DISCOVERY]",
                            "instruction": (
                                "Review the dossier. Send `[APPROVE_DISCOVERY]` to "
                                "continue to planning, or `[APPROVE_DISCOVERY] "
                                "{\"domain\": \"…\", \"complianceNotes\": [\"…\"]}` "
                                "with edits."
                            ),
                        })
                        yield sse_event("complete", {
                            "project_id": str(project.id), "intent": "DISCOVERY",
                        })
                        return

                yield sse_event("intent", {"intent": "PLAN", "reasoning": "No code yet — gathering requirements"})
                yield sse_event("status", {"message": "Planning your application..."})

                # Load conversation history for multi-turn context
                conversation_history = await _load_conversation_history(project.id)

                from services.domain_context import detect_domain
                domain_ctx = detect_domain(req_local.message)
                # Planner on the Anthropic SDK (same reliable transport as discovery, ~90s)
                # instead of the bundled CLI which wedges/crawls. Returns a fully-sanitized
                # plan dict (_annotate_page_types applies the action + design sanitizers).
                # produce_plan() keeps this one-shot path byte-unchanged for small/medium
                # apps and routes large apps through skeleton→per-unit planning (with a
                # one-shot fallback if decomposition breaks). project.output_dir already
                # exists on disk (created at project creation) so the two-stage path can
                # materialize contracts/resource-registry.json.
                plan = None
                # JT-T4: attach structured brief (see analogous block above).
                _brief_for_planner = None
                try:
                    from services.brief_lookup import get_structured_brief_for_project
                    _brief_for_planner = await get_structured_brief_for_project(
                        db, project.id,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("[planner] structured-brief lookup failed")
                _fail_text = ""
                try:
                    async for _pkind, _ppayload in _stream_produce_plan(
                        req_local.message,
                        project.output_dir,
                        domain_context=domain_ctx,
                        structured_brief=_brief_for_planner,
                    ):
                        if _pkind == "event":
                            yield _ppayload
                        else:
                            plan = _ppayload
                except Exception as _pe:
                    logger.exception("[chat] planner (SDK) failed")
                    yield sse_event("log", {"text": f"[Planner] failed: {_pe}"})
                    # Visible failure — a bare `log` event leaves the chat
                    # silent (an empty assistant message was all the user saw
                    # when planning timed out). Say what happened + how to retry.
                    _fail_text = (
                        "Planning didn't finish — the plan stream was "
                        "interrupted before completion. Please send your "
                        "request again to retry."
                    )
                    yield sse_event("message", {"text": _fail_text})
                full_text = json.dumps(plan, indent=2) if plan else _fail_text

                # Inject register classification into plan before persisting.
                # LLM-driven (with rule-based fallback) — see classify_register_llm
                # in services/register_selector.py.
                if plan:
                    from agents.planner import classify_register_llm
                    brief = req_local.message or ""
                    plan["register"] = await classify_register_llm(
                        brief, plan.get("domain", ""), plan
                    )

                # Persist assistant message with plan in metadata if found
                metadata: dict = {"intent": "PLAN"}
                if plan:
                    metadata["plan"] = plan
                    # Emit design templates BEFORE plan_ready so the whole
                    # interactive step (themes + the plan's Begin Quest button)
                    # lands together and the stream is about to `complete` — the
                    # Begin Quest button is enabled immediately instead of being
                    # disabled for the seconds of template research after it
                    # appeared (the "click 4-5 times before it takes" bug).
                    async for _tev in _offer_design_templates(plan, project.output_dir):
                        yield _tev
                    yield sse_event("plan_ready", {"plan": plan})
                    _bp_record_plan(project, plan)

                await _persist_assistant_message(
                    project.id,
                    full_text,
                    MessageType.plan if plan else MessageType.chat,
                    metadata=metadata,
                )

                yield sse_event("complete", {"project_id": str(project.id), "intent": "PLAN"})
                return

            yield sse_event("intent", {
                "intent": intent,
                "reasoning": classification.get("reasoning", ""),
            })

            # Conversational Fix-Assistant — a symptom on a has-code project.
            # Recall → diagnose → propose (+ [APPLY_FIX] chip). Apply happens on
            # the follow-up [APPLY_FIX] message, handled above.
            # When FORGE_SMITH is on, route through the Smith agent instead —
            # broader tool palette + <smith-memory> across turns. The chip
            # flow ([APPLY_FIX]) short-circuits above regardless of the flag,
            # so the Apply UX is unaffected.
            if intent == "FIX" and project_has_code:
                if _smith_enabled():
                    async for _ev in _handle_smith_turn(project, req_local.message, current_route=getattr(req_local, "current_route", None), attachment_ids=getattr(req_local, "attachment_ids", None)):
                        yield _ev
                    yield sse_event("complete", {"project_id": str(project.id), "intent": "SMITH"})
                    return
                async for _ev in _handle_fix_proposal(project, req_local.message):
                    yield _ev
                yield sse_event("complete", {"project_id": str(project.id), "intent": "FIX"})
                return

            # Step 2: Handle non-agent intents directly
            if intent == "AMBIGUOUS":
                clarification = classification.get("clarification", "Could you be more specific?")
                await _persist_assistant_message(
                    project.id, clarification, MessageType.chat,
                )
                yield sse_event("message", {"text": clarification})
                yield sse_event("complete", {"project_id": str(project.id)})
                return

            if intent == "NAVIGATE":
                msg = classification.get("reasoning", "Navigating...")
                await _persist_assistant_message(
                    project.id, msg, MessageType.chat,
                    metadata={"intent": "NAVIGATE"},
                )
                yield sse_event("navigate", {
                    "reasoning": classification.get("reasoning", ""),
                })
                yield sse_event("complete", {"project_id": str(project.id)})
                return

            if intent == "UNDO":
                yield sse_event("status", {"message": "Reverting last change..."})
                commit_hash = await git_revert(project.output_dir)
                if commit_hash:
                    # Re-index after revert
                    from agents.indexer import run_indexer
                    async for evt in stream_agent_messages(
                        run_indexer(output_dir=project.output_dir),
                        output_dir=project.output_dir,
                        event_prefix="[Indexer] ",
                    ):
                        if evt.get("event") != "agent_result":
                            yield evt

                    await _persist_version(project.id, commit_hash, "Undo last change")
                    await _persist_assistant_message(
                        project.id, "Reverted the last change.",
                        MessageType.chat, metadata={"commit_hash": commit_hash},
                    )
                    yield sse_event("undo_complete", {"commit_hash": commit_hash})
                else:
                    await _persist_assistant_message(
                        project.id, "Nothing to undo.",
                        MessageType.chat,
                    )
                    yield sse_event("message", {"text": "Nothing to undo — no commits to revert."})
                yield sse_event("complete", {"project_id": str(project.id)})
                return

            # Step 3: Route to the appropriate specialist agent
            total_cost = 0
            total_turns = 0
            total_duration = 0

            agent_type = _INTENT_TO_AGENT_TYPE.get(intent, AgentType.refiner)
            # Give refines continuity: a short summary of the conversation so far.
            _convo_summary = ""
            try:
                _convo_summary = _summarize_conversation(await _load_conversation_history(project.id))
            except Exception:  # noqa: BLE001
                pass
            agent_messages = _get_agent_for_intent(
                intent, project.output_dir, req_local.message, _convo_summary,
            )

            yield sse_event("status", {"message": f"Running {intent.lower()} agent..."})

            async for evt in stream_agent_messages(
                agent_messages,
                output_dir=project.output_dir,
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            # Step 4: For code-changing intents, validate → index → commit
            commit_hash = None
            if intent in _CODE_CHANGING_INTENTS:
                # Smith edit — legitimate re-run on an already-generated
                # output_dir. Pass force=True so Phase 7's idempotency
                # guard doesn't warn+no-op.
                apply_post_generate_fixes(project.output_dir, force=True)
                # Sidebar sync — the shell menu is a derivative of nav-flow.json,
                # so whenever a code-changing agent (refine/scaffold/…) has
                # written new pages or removed old ones, we regenerate the
                # ``props.groups`` array in shell.json from the nav-flow. This
                # is what makes ``add a Recruiters feature`` actually put a
                # Recruiters entry in the sidebar without a follow-up ask.
                # Deterministic, idempotent, safe to run every time.
                # Per-role visibility backfill — reads actors + route
                # prefixes and stamps ``visibleTo`` on every nav-flow
                # page (SP menu-role slice). Must run BEFORE
                # sync_shell_menu so the aggregated `roles` on each
                # sidebar group is available for the runtime shell to
                # filter per current user. Silent on any error — a
                # missing plan or nav-flow makes it a no-op.
                try:
                    from services.page_visibility_derivation import derive_visible_to
                    derive_visible_to(project.output_dir)
                except Exception:  # noqa: BLE001
                    logger.exception("[page_visibility_derivation] failed")

                try:
                    from services.shell_menu_sync import sync_shell_menu
                    sync_shell_menu(project.output_dir)
                except Exception:  # noqa: BLE001
                    logger.exception("[shell_menu_sync] failed")
                yield sse_event("status", {"message": "Validating build..."})
                from agents.validator import run_validator
                async for evt in stream_agent_messages(
                    run_validator(output_dir=project.output_dir),
                    output_dir=project.output_dir,
                    event_prefix="[Validator] ",
                ):
                    if evt.get("event") == "agent_result":
                        data = json.loads(evt["data"])
                        total_cost += data.get("cost_usd", 0)
                        total_turns += data.get("num_turns", 0)
                        total_duration += data.get("duration_ms", 0)
                    else:
                        yield evt

                yield sse_event("status", {"message": "Indexing application..."})
                from agents.indexer import run_indexer
                async for evt in stream_agent_messages(
                    run_indexer(output_dir=project.output_dir),
                    output_dir=project.output_dir,
                    event_prefix="[Indexer] ",
                ):
                    if evt.get("event") == "agent_result":
                        data = json.loads(evt["data"])
                        total_cost += data.get("cost_usd", 0)
                        total_turns += data.get("num_turns", 0)
                        total_duration += data.get("duration_ms", 0)
                    else:
                        yield evt

                await _sync_pages_from_app_model(project.id, project.output_dir)
                commit_hash = await git_commit(
                    project.output_dir,
                    f"{intent.lower()}: {req_local.message[:80]}",
                    actor="generator",   # S24-9
                )

            # Step 5: Persist results
            from database import async_session
            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=agent_type,
                    status=AgentJobStatus.completed,
                    instruction=req_local.message,
                    result={
                        "intent": intent,
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "duration_ms": total_duration,
                    },
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                sess.add(job)
                await sess.flush()

                if commit_hash:
                    version = Version(
                        project_id=project.id,
                        commit_hash=commit_hash,
                        message=f"{intent.lower()}: {req_local.message[:80]}",
                        agent_job_id=job.id,
                    )
                    sess.add(version)

                # Files-changed count — best-effort from the last commit if we
                # have one; used to make the "Changes applied" text specific.
                _files_changed = 0
                if commit_hash:
                    try:
                        import subprocess
                        _r = subprocess.run(
                            ["git", "show", "--stat", "--format=", commit_hash],
                            cwd=project.output_dir, capture_output=True, text=True,
                            timeout=5,
                        )
                        if _r.returncode == 0:
                            _last = _r.stdout.strip().splitlines()[-1] if _r.stdout.strip() else ""
                            import re as _re
                            m = _re.search(r"(\d+)\s+files?\s+changed", _last)
                            if m:
                                _files_changed = int(m.group(1))
                    except Exception:  # noqa: BLE001
                        pass
                content = _response_text_for_intent(
                    intent,
                    commit_hash=commit_hash,
                    files_changed=_files_changed,
                )
                assistant_msg = Conversation(
                    project_id=project.id,
                    role=MessageRole.assistant,
                    content=content,
                    message_type=MessageType.plan if intent == "PLAN" else MessageType.chat,
                    metadata_={
                        "intent": intent,
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "commit_hash": commit_hash,
                        # verify-before-claim signal: when refine/scaffold ran
                        # but nothing landed, mark the message so the frontend
                        # can style it as a warning rather than a success.
                        "no_changes": (
                            intent in _CODE_CHANGING_INTENTS and not commit_hash
                        ),
                    },
                )
                sess.add(assistant_msg)
                await sess.commit()

            # Send the response as a message so the frontend adds it to chat history
            yield sse_event("message", {"text": content})

            # Offer the post-build chat actions (Seed demo data · Test/Validate/Repair)
            # so the user can populate the DB + test, then validate. Only for a full
            # app build (a commit was produced), not plan/chat turns.
            _post_actions = None
            try:
                if commit_hash and intent not in ("PLAN", "DESIGN_ANALYSIS"):
                    from services.post_gen_actions import post_build_actions
                    _post_actions = post_build_actions()
            except Exception:
                _post_actions = None

            yield sse_event("complete", {
                "project_id": str(project.id),
                "intent": intent,
                "num_turns": total_turns,
                "cost_usd": total_cost,
                "duration_ms": total_duration,
                "commit_hash": commit_hash,
                **({"actions": _post_actions} if _post_actions else {}),
            })

        except Exception as e:
            logger.exception("Error in /chat")
            yield sse_event("error", {"message": _unwrap_error(e)})

    return EventSourceResponse(
        buffered_event_stream(event_stream(), str(project_id)),
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Indexer refresh endpoint (called after visual editor changes)
# ---------------------------------------------------------------------------

@router.post("/api/projects/{project_id}/refresh-index")
async def refresh_index(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-run the indexer agent to refresh app-model.json after code changes.

    This is called by visual editors and agent builder after applying changes
    to ensure the app model stays up-to-date.
    """
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="Project has no output directory")

    async def event_stream():
        yield sse_event("status", {"message": "Refreshing application index..."})
        try:
            from agents.indexer import run_indexer
            async for evt in stream_agent_messages(
                run_indexer(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Indexer] ",
            ):
                if evt.get("event") != "agent_result":
                    yield evt

            await _sync_pages_from_app_model(project.id, project.output_dir)
            yield sse_event("complete", {"project_id": str(project.id)})
        except Exception as e:
            logger.exception("Error refreshing index for project %s", project_id)
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarize_conversation(history: list[dict], max_turns: int = 6) -> str:
    """Compact the last few turns into a prompt-friendly summary so the refiner
    has continuity of earlier changes."""
    lines: list[str] = []
    for m in (history or [])[-max_turns:]:
        role = "User" if m.get("role") == "user" else "Assistant"
        content = " ".join((m.get("content") or "").split())
        if not content or content.startswith("["):  # skip control signals like [APPROVE_PLAN]
            continue
        if len(content) > 240:
            content = content[:240] + "…"
        lines.append(f"- {role}: {content}")
    return "\n".join(lines)


def _get_agent_for_intent(intent: str, output_dir: str, message: str, conversation_summary: str = ""):
    """Return the appropriate agent async generator for the given intent."""
    if intent == "PLAN":
        from agents.planner import run_planner
        from services.domain_context import detect_domain
        return run_planner(output_dir=output_dir, user_message=message, domain_context=detect_domain(message))
    elif intent == "REFINE":
        from agents.refiner import run_refiner
        return run_refiner(output_dir=output_dir, instruction=message, conversation_summary=conversation_summary)
    elif intent == "EXPLAIN":
        from agents.explainer import run_explainer
        return run_explainer(output_dir=output_dir, question=message)
    elif intent in ("SCAFFOLD", "AGENT"):
        from agents.scaffolder import run_scaffolder
        return run_scaffolder(output_dir=output_dir, instruction=message)
    elif intent == "DISCOVER":
        from agents.planner import run_planner
        from services.domain_context import detect_domain
        return run_planner(output_dir=output_dir, user_message=message, domain_context=detect_domain(message))
    else:
        # Default fallback: refiner
        from agents.refiner import run_refiner
        return run_refiner(output_dir=output_dir, instruction=message, conversation_summary=conversation_summary)


def _response_text_for_intent(
    intent: str,
    *,
    commit_hash: str | None = None,
    files_changed: int = 0,
) -> str:
    """Generate a summary message for the assistant based on intent.

    Verify-before-claim: for code-changing intents (REFINE/SCAFFOLD/
    AGENT), refuse the "successfully" wording when the refiner ran but
    produced no observable change — ``commit_hash`` is None because
    ``git_commit`` returned None on an empty diff. Speaking success on
    a no-op is the exact class of bug that made "Changes applied
    successfully" appear over an empty Agent tab.

    ``files_changed`` is optional context for a richer message when the
    caller has counted the diff shape (not required — commit_hash alone
    is the source-of-truth signal).
    """
    if intent in _CODE_CHANGING_INTENTS and not commit_hash:
        return (
            "I looked into that but couldn't apply a change — the ask was "
            "too broad for my current seams to act on, so nothing landed. "
            "Try breaking it into smaller, specific pieces — for example, "
            "*add a page /assistant*, then *add an AI chat component to it*. "
            "I'll apply each step reliably."
        )
    messages = {
        "PLAN": "Here's a structured plan for your application.",
        "REFINE": (
            f"Changes applied — {files_changed} file(s) updated."
            if files_changed
            else "Changes applied."
        ),
        "EXPLAIN": "Explanation complete.",
        "SCAFFOLD": "New feature added.",
        "AGENT": "Agent feature scaffolded.",
    }
    return messages.get(intent, "Done.")


def _bp_record_plan(project, plan: dict | None) -> None:
    """Blueprint-write hook for plan_ready sites (spec §6.3).

    Called wherever the pipeline emits a plan_ready SSE event.
    Idempotent (per-name skip in ``record_plan``) so calling twice
    per turn is safe. Any failure is swallowed by the hook."""
    try:
        if not plan or not isinstance(plan, dict) or not project or not project.output_dir:
            return
        from services.blueprint_pipeline_hooks import record_plan as _record_plan
        _record_plan(
            output_dir=project.output_dir,
            project_id=str(project.id),
            plan=plan,
        )
    except Exception:  # noqa: BLE001
        logger.exception("[blueprint] plan hook failed")


def _bp_record_generation_complete(project, files: list[str], user_ask: str) -> None:
    """Blueprint change_log hook fired once per generation run."""
    try:
        if not project or not project.output_dir:
            return
        from services.blueprint_pipeline_hooks import (
            record_generation_complete as _record_gen,
        )
        _record_gen(
            output_dir=project.output_dir,
            project_id=str(project.id),
            files=list(files or []),
            user_ask=user_ask or "",
        )
    except Exception:  # noqa: BLE001
        logger.exception("[blueprint] generation-complete hook failed")


async def _persist_assistant_message(
    project_id: uuid.UUID,
    content: str,
    message_type: MessageType,
    metadata: dict | None = None,
) -> None:
    """Persist an assistant message in a new DB session.

    Also fans out on the project event bus as a ``self_heal_message`` so
    the ChatPanel's already-listening EventSource can upsert the new row
    immediately — otherwise messages written from a background task
    (verify-complete, self-heal terminal state, etc.) sit in the DB
    invisible until the user refreshes the page.
    """
    from database import async_session
    async with async_session() as sess:
        msg = Conversation(
            project_id=project_id,
            role=MessageRole.assistant,
            content=content,
            message_type=message_type,
            metadata_=metadata,
        )
        sess.add(msg)
        await sess.commit()
        await sess.refresh(msg)
        # Fan out on the project event bus. Never fail the persist over
        # a delivery hiccup — the message is already durably in the DB.
        try:
            from services.project_event_bus import publish as _bus_publish
            await _bus_publish(str(project_id), {
                "type": "self_heal_message",
                "conversation_id": str(msg.id),
                "role": msg.role.value,
                "content": msg.content,
                "message_type": msg.message_type.value,
                "metadata": msg.metadata_,
                "created_at": (msg.created_at.isoformat()
                               if msg.created_at else None),
            })
        except Exception:  # noqa: BLE001
            logger.exception(
                "[_persist_assistant_message] event bus publish failed for %s",
                project_id,
            )


async def _load_conversation_history(project_id: uuid.UUID) -> list[dict]:
    """Load the full conversation history for a project."""
    from database import async_session
    async with async_session() as sess:
        result = await sess.execute(
            select(Conversation)
            .where(Conversation.project_id == project_id)
            .order_by(Conversation.created_at)
        )
        return [
            {"role": c.role.value, "content": c.content}
            for c in result.scalars()
        ]


async def _load_pending_plan(project_id: uuid.UUID) -> dict | None:
    """Load the most recent plan from assistant message metadata.

    First checks metadata for a stored plan. If not found, attempts to
    re-extract from the message content (handles cases where initial
    extraction failed due to minor JSON errors).
    """
    from database import async_session
    async with async_session() as sess:
        result = await sess.execute(
            select(Conversation)
            .where(
                Conversation.project_id == project_id,
                Conversation.role == MessageRole.assistant,
            )
            .order_by(Conversation.created_at.desc())
            .limit(10)
        )
        conversations = list(result.scalars())

        # Pass 1: check metadata for stored plan
        for conv in conversations:
            if conv.metadata_ and isinstance(conv.metadata_, dict):
                plan = conv.metadata_.get("plan")
                if plan:
                    logger.info(f"[plan] Found plan in metadata of message {conv.id}")
                    return plan

        # Pass 2: re-extract from content (handles earlier extraction failures)
        for conv in conversations:
            if conv.content and "```plan-json" in conv.content:
                plan = _extract_plan_json(conv.content)
                if plan:
                    logger.info(f"[plan] Re-extracted plan from content of message {conv.id}")
                    # Back-fill the metadata so future lookups are faster
                    meta = dict(conv.metadata_) if conv.metadata_ else {}
                    meta["plan"] = plan
                    conv.metadata_ = meta
                    await sess.commit()
                    return plan

    logger.warning(f"[plan] No plan found for project {project_id}")
    return None


async def _load_pending_plan_with_metadata(project_id: uuid.UUID) -> tuple[dict | None, dict | None]:
    """Load the most recent plan and its full metadata from assistant message.

    Returns (plan_dict, full_metadata_dict). The metadata may contain
    figma_url, figma_token, intent, etc.
    """
    from database import async_session
    async with async_session() as sess:
        result = await sess.execute(
            select(Conversation)
            .where(
                Conversation.project_id == project_id,
                Conversation.role == MessageRole.assistant,
            )
            .order_by(Conversation.created_at.desc())
            .limit(10)
        )
        conversations = list(result.scalars())

        for conv in conversations:
            if conv.metadata_ and isinstance(conv.metadata_, dict):
                plan = conv.metadata_.get("plan")
                if plan:
                    return plan, conv.metadata_

        # Pass 2: re-extract from content
        for conv in conversations:
            if conv.content and "```plan-json" in conv.content:
                plan = _extract_plan_json(conv.content)
                if plan:
                    meta = dict(conv.metadata_) if conv.metadata_ else {}
                    meta["plan"] = plan
                    conv.metadata_ = meta
                    await sess.commit()
                    return plan, meta

    return None, None


# ── Conversational Fix-Assistant (Task 1-D) ─────────────────────────────────
# A FIX-intent message → recall + diagnose → stream a `fix_proposal` + an
# `[APPLY_FIX]` chip; the diagnosis is stashed in the assistant turn's
# `metadata_["pending_fix"]`. On a follow-up `[APPLY_FIX]` message we retrieve
# that Diagnosis and apply it via the deterministic seam, streaming
# `fix_applied`. Everything rides the existing conversation/session/SSE machinery.

# A diagnosis below this confidence (or one that localizes nothing) is surfaced
# as a clarifying question instead of an apply-able proposal.
_FIX_MIN_CONFIDENCE = 0.35

# A/B log entry builders — every fix-related persist attaches a `fix_ab` dict so
# we can compare the agent path vs the single-shot handler head-to-head.
from services.fix_ab_log import (  # noqa: E402
    build_applied_entry, build_clarify_entry, build_error_entry, build_propose_entry,
)


def _elapsed_ms(t0: float) -> int:
    """Milliseconds since a `time.monotonic()` reading. Kept inline so the
    handlers can attach an `elapsed_ms` field to every fix_ab record."""
    return int((time.monotonic() - t0) * 1000)


# The model's proposal text sometimes reads as past-tense ("Both are fixed in
# the patch above") which is misleading — the fix is only a PROPOSAL until the
# user clicks Apply. Normalize the explanation so it (a) reads as a proposal,
# not an accomplishment, and (b) always ends with a clear call-to-action.
_PAST_TENSE_FIX_RE = re.compile(
    r"\b(is|are|were|have\s+been|has\s+been|got|got\s+been|been)\s+"
    r"(fixed|corrected|updated|resolved|patched|rebound|repointed|changed|"
    r"replaced|amended|repaired)\b",
    re.IGNORECASE,
)
_APPLIED_ASSERTION_RE = re.compile(
    r"\b(?:has|have|is|are)\s+been\s+applied\b|"
    r"\bnow\s+works?\b|"
    r"\ball\s+set\b|"
    r"\ball\s+(?:done|good)\b",
    re.IGNORECASE,
)
_APPLY_CTA = "\n\nNote: I haven't applied this yet — click **Apply fix** above to make the change."


def _normalize_proposal_text(text: str) -> str:
    """Make a proposal explanation read as a proposal, not as an already-applied
    change. Rewrites past-tense fix claims to conditional form and appends a
    clear apply-me hint (idempotent — won't double up if the hint is present)."""
    if not text:
        return "I have a fix ready — click **Apply fix** above to apply it."
    out = _PAST_TENSE_FIX_RE.sub(lambda m: f"will be {m.group(2).lower()}", text)
    out = _APPLIED_ASSERTION_RE.sub("will apply once you click Apply", out)
    if "apply fix" not in out.lower() and "click apply" not in out.lower():
        out = out.rstrip() + _APPLY_CTA
    return out

# Short affirmative openers: if the WHOLE message starts with any of these
# (after normalizing punctuation/case), treat it as consent to apply a pending
# proposal rather than a new symptom. Keep the list conservative — a symptom
# sentence that just happens to contain "fix" (e.g. "the fix doesn't work") must
# NOT match, so we require the phrase to appear at the very start and the
# message to be short-ish or end with a filler word.
_APPLY_INTENT_STARTS = (
    "yes", "yep", "yeah", "yup", "sure", "ok", "okay",
    "go ahead", "go", "do it", "proceed", "apply",
    "fix it", "fix", "please fix", "please apply", "please do", "please",
    "can you fix", "can you apply", "can you please fix", "can you please apply",
)
_APPLY_INTENT_FILLERS = {"please", "it", "the", "fix", "please.", "it.", "!", "?", "."}
_PUNCT_STRIP_RE = re.compile(r"[\?\!\.\,]+$")


def _fix_agent_enabled() -> bool:
    """FORGE_FIX_AGENT gates the agentic reasoning loop (Slice 3). Off by
    default → single-shot handler (byte-identical to pre-agent behaviour)."""
    from services.flag_profile import is_on
    return is_on("FORGE_FIX_AGENT")


def _smith_enabled() -> bool:
    """FORGE_SMITH gates Smith — the conversational build/fix assistant. Off
    by default → the FIX branch keeps routing through _handle_fix_proposal.
    On → free-form post-build turns route through _handle_smith_turn, which
    owns the <smith-memory> context engine + the propose_fix/answer/ask_user
    terminals.

    Chip tokens ([APPLY_FIX], [APPROVE_PLAN], [SELECT_TEMPLATE:*]) short-
    circuit BEFORE the Smith gate, so the Apply-fix flow is unaffected
    regardless of the flag."""
    from services.flag_profile import is_on
    return is_on("FORGE_SMITH")


# Greeting / small-talk detector — used by the no-code Smith gate. Kept
# conservative on purpose: a real app description ("Build a patient
# management system for a clinic") must NOT match, or we'd hijack the
# discovery pipeline. A "Hi" or "what can you do?" MUST match, or Smith
# feels non-conversational on a fresh project.
_GREETING_RE = re.compile(
    r"^\s*("
    r"hi|hello|hey|yo|sup|howdy|"
    r"good\s+(morning|afternoon|evening|day)|"
    r"greetings|hola|salaam|salam|"
    r"who\s+are\s+you|what\s+can\s+you\s+do|what\s+do\s+you\s+do|"
    r"how\s+does\s+this\s+work|help|"
    r"who\s+is\s+smith|what\s+is\s+smith"
    r")\s*[!?.,]*\s*$",
    re.IGNORECASE,
)

_MAX_CONVERSATIONAL_WORDS = 5
"""A message with more than this many words is presumed to be a real request
(build description, refinement, symptom) rather than a greeting."""


def _make_forwarded_request(orig, new_message: str):
    """Return a shallow copy of the incoming chat request with ``message``
    replaced by ``new_message`` — used by the Smith-handoff fall-through so
    the downstream pipeline dispatcher sees the message Smith forwarded
    rather than the user's original (which may have been a greeting or a
    freeform description Smith rephrased for the pipeline)."""
    try:
        # pydantic v2
        return orig.model_copy(update={"message": new_message})
    except Exception:  # noqa: BLE001
        # Fall back to attribute mutation (still a shallow view; sufficient
        # because we only read `message` downstream).
        try:
            return orig.copy(update={"message": new_message})
        except Exception:  # noqa: BLE001
            orig.message = new_message  # type: ignore[assignment]
            return orig


def _looks_conversational(message: str) -> bool:
    """True when the message reads as small-talk / a greeting rather than
    an app description or a symptom. Pre-classifier — we want to intercept
    these BEFORE classify_intent decides they're PLAN/DISCOVER on a fresh
    project and jumps straight into the discovery pipeline (bypassing
    Smith entirely, which is what happened before this gate)."""
    if not isinstance(message, str):
        return False
    norm = message.strip()
    if not norm:
        return False
    if _GREETING_RE.match(norm):
        return True
    # Very short messages with no build/create/add/fix/change verb → treat as
    # conversational so Smith can ask what they want (long "Build me an X"
    # requests still flow into the planner unchanged).
    words = norm.split()
    if len(words) <= _MAX_CONVERSATIONAL_WORDS:
        build_words = {"build", "create", "make", "generate", "scaffold",
                       "add", "fix", "change", "remove", "delete", "update"}
        if not any(w.lower().rstrip(",.!?") in build_words for w in words):
            return True
    return False


def _looks_like_apply_intent(message: str) -> bool:
    """True when the user's message reads as consent to apply a pending proposal
    (rather than a new symptom). Kept conservative — the phrase must appear at
    the very start AND the remainder must be short filler ("yes please", "fix
    it", "apply") so long symptom sentences containing "fix" won't match."""
    if not message:
        return False
    norm = _PUNCT_STRIP_RE.sub("", message.strip().lower()).strip()
    if not norm:
        return False
    for opener in _APPLY_INTENT_STARTS:
        if norm == opener:
            return True
        if norm.startswith(opener + " "):
            tail = norm[len(opener) + 1:].split()
            if all(w.rstrip(".!?") in _APPLY_INTENT_FILLERS for w in tail):
                return True
    return False


def _find_pending_fix(conversations: list) -> dict | None:
    """Return the most recent stashed Diagnosis from a list of Conversation-like
    objects (each with a ``metadata_`` dict), newest-first, or None.

    Pure — no DB — so the store/retrieve round-trip is unit-testable.

    Two sources are checked, in priority order:
      1. ``metadata.pending_fix`` — the canonical spot the single-shot fix
         path stashes at (see ``_pending_fix_metadata``).
      2. ``metadata.smith_trace[*].tool == 'propose_fix'`` — the trace
         entries the Smith tool-loop leaves behind. The persist path
         doesn't lift ``args.diagnosis`` to top-level ``pending_fix``,
         so a Smith-diagnosed FixProposal is otherwise invisible to the
         apply flow. Newest propose_fix in the newest matching turn
         wins (mirrors the frontend's fallback in ChatMessage.tsx).
    """
    for conv in conversations or []:
        md = getattr(conv, "metadata_", None)
        if not isinstance(md, dict):
            continue
        pending = md.get("pending_fix")
        if isinstance(pending, dict):
            return pending
        # Fallback — reach into the Smith tool trace.
        trace = md.get("smith_trace")
        if isinstance(trace, list):
            for step in reversed(trace):
                if not isinstance(step, dict):
                    continue
                if step.get("tool") == "propose_fix":
                    args = step.get("args")
                    if isinstance(args, dict):
                        diagnosis = args.get("diagnosis")
                        if isinstance(diagnosis, dict):
                            return diagnosis
    return None


def _pending_fix_metadata(diagnosis: dict, mode: str | None = None) -> dict:
    """The assistant-turn metadata that stashes a pending fix (pure). ``mode`` is
    the A/B attribution ("agent" / "single_shot") — apply-time reads it so the
    ``applied`` fix_ab record is bucketed under the mode that produced the fix."""
    meta = {
        "intent": "FIX",
        "pending_fix": diagnosis,
        "applyToken": FIX_APPLY_TOKEN,
    }
    if mode:
        meta["pending_fix_mode"] = mode
    return meta


def _find_pending_fix_mode(conversations: list) -> str | None:
    """Mode ("agent"/"single_shot") from the most recent assistant turn that
    stashed a pending_fix. Symmetric with `_find_pending_fix` — checks both
    top-level ``pending_fix`` and ``smith_trace[*].propose_fix``. Smith-driven
    proposals are attributed to "agent"."""
    for conv in conversations or []:
        md = getattr(conv, "metadata_", None)
        if not isinstance(md, dict):
            continue
        if isinstance(md.get("pending_fix"), dict):
            mode = md.get("pending_fix_mode")
            if isinstance(mode, str) and mode:
                return mode
            return None  # first pending wins; missing mode → unknown
        # Fallback: a Smith trace with a propose_fix is agent-mode by construction.
        trace = md.get("smith_trace")
        if isinstance(trace, list):
            for step in reversed(trace):
                if isinstance(step, dict) and step.get("tool") == "propose_fix":
                    return "agent"
    return None


async def _load_pending_fix(project_id: uuid.UUID) -> dict | None:
    """Load the most recent pending Diagnosis from assistant message metadata."""
    from database import async_session
    async with async_session() as sess:
        result = await sess.execute(
            select(Conversation)
            .where(
                Conversation.project_id == project_id,
                Conversation.role == MessageRole.assistant,
            )
            .order_by(Conversation.created_at.desc())
            .limit(10)
        )
        return _find_pending_fix(list(result.scalars()))


async def _load_pending_fix_mode(project_id: uuid.UUID) -> str | None:
    """Load the A/B mode ("agent"/"single_shot") of the current pending fix, or
    None if unknown/absent. Used at apply-time to attribute the applied fix_ab
    record to the mode that produced the proposal."""
    from database import async_session
    async with async_session() as sess:
        result = await sess.execute(
            select(Conversation)
            .where(
                Conversation.project_id == project_id,
                Conversation.role == MessageRole.assistant,
            )
            .order_by(Conversation.created_at.desc())
            .limit(10)
        )
        return _find_pending_fix_mode(list(result.scalars()))


async def _clear_pending_fix(project_id: uuid.UUID) -> None:
    """Strip ``pending_fix`` from any recent assistant turns (post-apply)."""
    from database import async_session
    async with async_session() as sess:
        result = await sess.execute(
            select(Conversation)
            .where(
                Conversation.project_id == project_id,
                Conversation.role == MessageRole.assistant,
            )
            .order_by(Conversation.created_at.desc())
            .limit(10)
        )
        touched = False
        for conv in result.scalars():
            if isinstance(conv.metadata_, dict) and "pending_fix" in conv.metadata_:
                meta = dict(conv.metadata_)
                meta.pop("pending_fix", None)
                conv.metadata_ = meta
                touched = True
        if touched:
            await sess.commit()


def _preview_fix_changes(output_dir: str, diagnosis: dict) -> list[dict]:
    """Best-effort preview of what the proposed fix WILL change (pre-apply).

    For a ``workflow_node_config`` fix, diff the node's current ``values``
    against the proposed values → ``[{node, field, from, to}]``. For a
    ``page_schema_patch`` fix, echo the RFC-6902 op list. Never raises.
    """
    try:
        proposed = (diagnosis or {}).get("proposedFix") or {}
        seam = proposed.get("seam")
        patch = proposed.get("patch")
        artifact = (diagnosis or {}).get("artifact") or {}
        rel_path = artifact.get("path")

        if seam == "workflow_node_config" and isinstance(patch, dict):
            node_id = ((diagnosis or {}).get("locator") or {}).get("nodeId")
            proposed_values = patch.get("values")
            if not isinstance(proposed_values, dict) or not rel_path or not node_id:
                return []
            before: dict = {}
            wf_path = Path(output_dir) / rel_path
            if wf_path.exists():
                try:
                    defn = (json.loads(wf_path.read_text()).get("definition") or {})
                    for n in (defn.get("nodes") or []):
                        if isinstance(n, dict) and n.get("id") == node_id:
                            cfg = (n.get("data") or {}).get("config") or {}
                            vals = cfg.get("values")
                            before = dict(vals) if isinstance(vals, dict) else {}
                            break
                except (OSError, ValueError):
                    before = {}
            changes: list[dict] = []
            for field in sorted(set(before) | set(proposed_values)):
                b = before.get(field)
                a = proposed_values.get(field)
                if b != a:
                    changes.append({"node": node_id, "field": field, "from": b, "to": a})
            return changes

        if seam == "page_schema_patch" and isinstance(patch, list):
            return [{"artifact": rel_path, "ops": patch}]
    except Exception:  # noqa: BLE001 — a preview must never break the proposal
        logger.exception("[fix] change-preview failed")
    return []


async def _handle_fix_proposal_agent(
    project: Project,
    symptom: str,
    pending: dict | None,
    recall,
    output_dir: str,
):
    """Agentic (Slice 3) branch of the FIX intent — a reasoning loop over the
    curated tool palette. Emits the same ``fix_proposal`` / ``message`` events
    the frontend already consumes; the agent's ``trace`` is attached to the
    assistant turn's metadata under ``fix_agent_trace``.

    The pending-fix / apply-intent short-circuit ran BEFORE this function is
    called — so on a low-confidence outcome with a pending proposal we still
    re-emit the pending (never silently drop a good proposal)."""
    _t0 = time.monotonic()  # A/B log: agent-turn elapsed
    try:
        recall_block = recall.to_prompt_block() if recall is not None else ""
    except Exception:  # noqa: BLE001
        recall_block = ""

    try:
        from agents.fix_chat_agent import run_fix_agent
        result = await asyncio.to_thread(
            run_fix_agent, symptom, output_dir, recall_block,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("[fix] agent loop failed")
        msg = ("I hit an error while diagnosing that. Could you describe the "
               "exact screen and what you clicked?")
        await _persist_assistant_message(
            project.id, msg, MessageType.chat,
            metadata={"intent": "FIX", "fix_ab": build_error_entry(
                mode="agent", symptom=symptom, elapsed_ms=_elapsed_ms(_t0),
            )},
        )
        yield sse_event("message", {"text": msg})
        return

    diagnosis = result.get("diagnosis") if isinstance(result, dict) else None
    question = result.get("question") if isinstance(result, dict) else None
    trace = result.get("trace") if isinstance(result, dict) else []

    if diagnosis:
        # Confident, structured proposal → stash + stream fix_proposal + chip.
        changes = _preview_fix_changes(output_dir, diagnosis)
        explanation = diagnosis.get("explanation") or (
            "I found the likely cause and can fix it."
        )
        metadata = _pending_fix_metadata(diagnosis, mode="agent")
        metadata["fix_agent_trace"] = trace
        metadata["fix_ab"] = build_propose_entry(
            mode="agent", symptom=symptom, diagnosis=diagnosis,
            trace=trace, elapsed_ms=_elapsed_ms(_t0),
        )
        await _persist_assistant_message(
            project.id, explanation, MessageType.chat, metadata=metadata,
        )
        yield fix_proposal_event(diagnosis, changes)
        yield sse_event("message", {"text": _normalize_proposal_text(explanation)})
        return

    # No structured diagnosis. If a prior proposal is still pending, re-emit it
    # so a fresh clarifying-only turn doesn't drop a good fix (parity with the
    # single-shot handler's low-confidence branch).
    if pending:
        changes = _preview_fix_changes(output_dir, pending)
        explanation = (pending.get("explanation") or
                       "Here's the fix I proposed. Click Apply to confirm.")
        metadata = _pending_fix_metadata(pending, mode="agent")
        metadata["fix_agent_trace"] = trace
        metadata["fix_ab"] = build_propose_entry(
            mode="agent", symptom=symptom, diagnosis=pending,
            trace=trace, elapsed_ms=_elapsed_ms(_t0), phase="reemit",
        )
        await _persist_assistant_message(
            project.id, explanation, MessageType.chat, metadata=metadata,
        )
        yield fix_proposal_event(pending, changes)
        yield sse_event("message", {"text": _normalize_proposal_text(explanation)})
        return

    # Otherwise the agent ended with a clarifying question (or a forced one).
    clarify = question or (
        "I couldn't pin that down to a specific screen or workflow. "
        "Could you tell me which page you were on and the exact error you saw?"
    )
    await _persist_assistant_message(
        project.id, clarify, MessageType.chat,
        metadata={"intent": "FIX", "fix_agent_trace": trace, "fix_ab": build_clarify_entry(
            mode="agent", symptom=symptom, trace=trace, elapsed_ms=_elapsed_ms(_t0),
        )},
    )
    yield sse_event("message", {"text": clarify})


async def _handle_smith_turn(project: Project, message: str, deferred: dict | None = None, current_route: str | None = None, attachment_ids: list[str] | None = None):
    """FORGE_SMITH turn — the conversational build/fix assistant.

    Runs the Smith reasoning loop with the app's recall + the cross-turn
    memory block, and dispatches based on which terminal fires:

      - ``diagnosis`` → same payload as the fix agent's confident-proposal
        path: FixProposalCard + [APPLY_FIX] chip + pending_fix stashed on
        the turn. The frontend re-uses its existing renderers.
      - ``handoff``   → Smith called ``handoff_to_pipeline(kind, message)``.
        Populates the caller-supplied ``deferred`` dict with
        ``{"handoff": {"kind": ..., "message": ...}}`` so the outer router
        can continue into the discovery / planner / refiner branch after
        Smith yields a short "handing off…" narration.
      - ``answer``    → plain message. Smith replied without a code change
        (e.g. "explain how X works").
      - ``question``  → plain message. Smith asked a clarifying question.

    The full agent trace is streamed as ``smith_thought`` events (one per
    tool call) BEFORE the terminal event, so the UI can render a compact
    "Thinking…" chip above the final response. The trace is also stashed
    on the turn's metadata as ``smith_trace`` for post-hoc inspection.

    Pending-fix short-circuit runs FIRST — the router will treat an
    affirmative-apply message ("yes / fix it") as [APPLY_FIX] rather than
    a new Smith turn (same rule the fix-agent branch uses)."""
    output_dir = project.output_dir
    _t0 = time.monotonic()

    # (a) Consent-to-apply on a pending proposal → route to apply. Mirrors
    # _handle_fix_proposal's short-circuit exactly — the Smith memory would
    # tell the loop the same thing, but skipping straight to apply saves
    # a model round-trip AND keeps FORGE_SMITH byte-compatible with the
    # existing chip flow.
    pending = await _load_pending_fix(project.id)
    if pending and _looks_like_apply_intent(message):
        async for _ev in _handle_apply_fix(project):
            yield _ev
        return

    # Amend requirement.json with the incoming turn (Slice 2 of
    # requirement-as-central-piece). Preserves the user's ask across
    # every follow-up so the fidelity critic (Slice 3) can score the
    # shipped app against the WHOLE requirement, not just the original
    # prompt. Skips trivial acknowledgements + apply-intents to keep
    # amendments meaningful.
    if isinstance(message, str) and len(message.strip()) > 8 and \
       not _looks_like_apply_intent(message):
        try:
            from services.requirement import amend_requirement
            amend_requirement(output_dir, message, who="user")
        except Exception as _amend_exc:  # noqa: BLE001
            logger.debug("[smith] requirement amend skipped: %s", _amend_exc)

    yield sse_event("status", {"message": "Smith is thinking..."})

    # Assemble the two context blocks the agent needs.
    recall_block = ""
    try:
        from services.app_recall import assemble_recall
        recall = assemble_recall(output_dir)
        recall_block = recall.to_prompt_block()
    except Exception:  # noqa: BLE001
        logger.exception("[smith] assemble_recall failed")

    memory_block = ""
    prior_messages: list[dict] = []
    try:
        from services.smith_memory import read_smith_memory, load_chat_history_for_prompt
        from database import async_session
        async with async_session() as sess:
            # CTX-1: pass output_dir so read_smith_memory can build a
            # focal resource-registry slice for the last-touched route
            # (so "the button doesn't work" doesn't blank-slate Smith).
            memory = await read_smith_memory(
                sess, project.id, output_dir=output_dir,
            )
            memory_block = memory.to_prompt_block()

            # Phase 1c — inject the user's durable preferences (persisted
            # across sessions) so Smith applies standing rules ("always
            # confirm on delete", "prefer purple") without the user
            # restating them each turn. Silent when the user has no
            # preferences set. Feature-flag-free — the query hits an
            # empty table on projects that never called set_preference.
            try:
                from services.smith_preferences import (
                    get_all as _get_prefs,
                    render_preferences_block,
                )
                user_id_val = getattr(project, "created_by", None) or getattr(project, "user_id", None)
                if user_id_val is not None:
                    _prefs = await _get_prefs(
                        sess, project.org_id, user_id_val,
                    )
                    _prefs_block = render_preferences_block(_prefs)
                    if _prefs_block:
                        memory_block = (
                            (memory_block + "\n\n") if memory_block else ""
                        ) + _prefs_block
            except Exception:
                logger.exception("[smith] smith_preferences read failed")

            # CTX-thread: also load prior chat turns in the messages
            # protocol shape (proper user/assistant alternation) so
            # follow-ups like "did you fix it?" resolve their referent
            # natively — flattened memory bullets don't cut it. Both
            # paths render; the model gets the same info as chat AND as
            # reference material.
            prior_messages = await load_chat_history_for_prompt(
                sess, project.id, message, limit=6,
            )
    except Exception:  # noqa: BLE001
        logger.exception("[smith] read_smith_memory failed")

    # CTX-2 / SMITH-SEARCH-1 wiring: extract proper-noun entity references
    # from the user's message and prepend a "Grounding" block that names each
    # matched entity + one-line graph summary. Silent when nothing matches.
    # Runs BEFORE Smith's loop so on turn 0 he already knows which entity
    # the ask is about — no wasted grep/read_page hunt.
    try:
        from services.smith_grounding import extract_grounding_hints
        grounding = extract_grounding_hints(message, output_dir)
        if grounding:
            memory_block = f"{grounding}\n{memory_block}" if memory_block else grounding
    except Exception:  # noqa: BLE001
        logger.exception("[smith] grounding pre-processor failed")

    # SMITH-VERIFY: whole-app verification asks ("verify and fix the app",
    # "does it work", "test everything") are intentionally BROAD — no
    # single screen. Skip the scope-check gate entirely and fire the
    # Self-Verify Pass directly. Smith's verify_app tool exists for the
    # in-loop path, but end users asking in plain language get the direct
    # route so we don't fall through to a screen-picking clarification.
    try:
        from agents.smith_agent import _is_verify_intent as _is_verify
        if _is_verify(message):
            from services.self_verify_pass import run_self_verify
            import asyncio as _asyncio_sv
            # _handle_smith_turn doesn't receive the authenticated user
            # object; the VerifyRun.triggered_by column is optional, so
            # None is fine (invoked_by="user_chat" is enough audit trail).

            _proj_id_for_verify = str(project.id)

            async def _run_verify_then_summarize():
                """Fire-and-forget wrapper: run the pass, then persist a
                rich completion message so Smith's next turn has full
                context (per-journey hints, autofix outcomes, fault list)
                without needing a tool call."""
                try:
                    from services.verify_summary import (
                        format_verify_report_json,
                        format_verify_summary,
                    )
                    from database import async_session as _async_session
                    from models.verify_run import VerifyRun as _VerifyRun
                    from sqlalchemy import select as _select, desc as _desc
                    import uuid as _uuid

                    # JV-27/#6 — parse a scope hint from the user's
                    # message so the "Current page" scope-picker option
                    # runs a fast, per-route verify instead of the whole
                    # app. Recognised patterns (case-insensitive):
                    #   "verify only the current page: /admin/foo"
                    #   "verify only the current page /admin/foo"
                    # Anything else defaults to scope="*".
                    _scope = "*"
                    try:
                        import re as _re_scope
                        m_scope = _re_scope.search(
                            r"current\s+page[:\s]+([/\w\-\[\]\.]+)",
                            message, _re_scope.IGNORECASE,
                        )
                        if m_scope:
                            _scope = m_scope.group(1).rstrip(".,")
                    except Exception:  # noqa: BLE001
                        pass
                    result = await run_self_verify(
                        _proj_id_for_verify, target="preview", scope=_scope,
                        fix=True, invoked_by="user_chat",
                    )
                    # Re-read the row for its latest state — run_self_verify
                    # returns a summary but not the full report we want.
                    async with _async_session() as _db:
                        row = None
                        run_id = (result or {}).get("run_id")
                        if run_id:
                            row = (await _db.execute(
                                _select(_VerifyRun).where(
                                    _VerifyRun.id == _uuid.UUID(run_id),
                                ),
                            )).scalar_one_or_none()
                        if row is None:
                            row = (await _db.execute(
                                _select(_VerifyRun)
                                .where(_VerifyRun.project_id ==
                                       _uuid.UUID(_proj_id_for_verify))
                                .order_by(_desc(_VerifyRun.created_at))
                                .limit(1),
                            )).scalar_one_or_none()
                        if row is None:
                            return
                        text = format_verify_summary(row)
                        # JV-27/B1 — structured payload for VerifyResultCard.
                        # top_n=40 hits the module-level clamp so all faults
                        # the runner reported land in the card (the plaintext
                        # `text` still summarizes to first 5 for Smith).
                        verify_payload = format_verify_report_json(row, top_n=40)
                        verify_payload["target"] = getattr(row, "target", "preview")
                        verify_payload["invoked_by"] = getattr(row, "invoked_by", "user_chat")
                        try:
                            created = getattr(row, "created_at", None)
                            completed = getattr(row, "completed_at", None)
                            if created and completed:
                                verify_payload["duration_ms"] = int(
                                    (completed - created).total_seconds() * 1000,
                                )
                        except Exception:  # noqa: BLE001
                            pass
                        # Carry the interaction_pass block through as-is —
                        # the card renders a subtle amber banner when
                        # `skipped=true` (runner sidecar unavailable).
                        verify_payload["interaction_pass"] = (
                            (getattr(row, "report", None) or {}).get(
                                "interaction_pass",
                            )
                        )
                    # Persist as `MessageType.chat` (adding a new enum value
                    # here would need a Postgres ALTER TYPE migration; the
                    # existing `discovery` pattern shows metadata-gating is
                    # sufficient — the frontend routes on `metadata.verify`).
                    await _persist_assistant_message(
                        _uuid.UUID(_proj_id_for_verify), text, MessageType.chat,
                        metadata={
                            "intent": "SMITH_VERIFY_COMPLETE",
                            "verify": verify_payload,
                            "run_id": str(getattr(row, "id", "") or ""),
                            "target": getattr(row, "target", "preview"),
                        },
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("[smith-verify] summary persistence failed")

            _asyncio_sv.create_task(_run_verify_then_summarize())
            _msg = (
                "Kicking off the Self-Verify Pass on your app — I'll walk "
                "every page + button in a real browser, classify any faults, "
                "then fix them in ≤3 rounds. You'll see the report land on "
                "the Verify chip when it finishes (typically 1–5 min "
                "depending on app size)."
            )
            await _persist_assistant_message(
                project.id, _msg, MessageType.chat,
                metadata={"intent": "SMITH_VERIFY_TRIGGER"},
            )
            yield sse_event("message", {"text": _msg})
            logger.info("[smith-verify] verify-intent detected → bypass scope-check + fire self-verify")
            return
    except Exception:  # noqa: BLE001
        logger.exception("[smith-verify] verify-intent bypass failed — falling through")

    # SMITH-SCOPE-1 (deterministic pre-filter): OFF by default (SA-confidence).
    # Historically this short-circuited whenever grounding matched an entity
    # with multiple pages, emitting a picker chip BEFORE the LLM ran — that
    # blocked every prompt-level "act confidently" improvement because Smith
    # never got the turn. Now gated: set FORGE_SMITH_SCOPE_PREFILTER=1 to
    # restore the old behaviour (useful when Smith is thrashing). Default
    # path: let Smith's own judgment (see routing prompt step 2a) decide.
    if os.getenv("FORGE_SMITH_SCOPE_PREFILTER", "0") == "1":
        try:
            from services.smith_grounding import build_deterministic_scope_check
            scope_prompt = build_deterministic_scope_check(message, output_dir)
            if scope_prompt:
                logger.info("[smith-scope] deterministic scope-check emitted (bypassing loop)")
                # Persist as an assistant message so it shows in chat + memory.
                await _persist_assistant_message(
                    project.id, scope_prompt, MessageType.chat,
                    metadata={"intent": "SMITH_SCOPE_CHECK", "smith_scope_check": True},
                )
                yield sse_event("message", {"text": scope_prompt})
                return
        except Exception:  # noqa: BLE001
            logger.exception("[smith] deterministic scope-check failed — falling through to loop")

    # SMITH-NAV: for menu/sidebar/nav asks, try a deterministic fix
    # BEFORE calling the LLM. When the ask is unambiguous (menu label
    # doesn't match its current route AND a page whose route matches
    # the label exists), we swap the route in shell.json ourselves and
    # report what was done. No user pick, no LLM turn — Smith "just
    # answers effectively". Ambiguous asks fall through with the menu
    # structure injected into the LLM's memory for a fast turn-0 answer.
    try:
        from services.smith_grounding import (
            _looks_like_nav_intent,
            try_fix_menu_route_mismatch,
            render_nav_context_block,
        )
        if _looks_like_nav_intent(message):
            nav_fix = try_fix_menu_route_mismatch(message, output_dir)
            if nav_fix and nav_fix.get("status") == "fixed":
                logger.info(
                    "[smith-nav] deterministic menu fix applied: %s",
                    nav_fix.get("edited_paths"),
                )
                # Commit the shell.json edit under Smith's authorship so
                # the change is traceable in git log alongside seam-based
                # fixes. Reuse the same commit helper the loop uses for
                # direct edits.
                try:
                    from services.fix_applier import _commit as _smith_commit
                    _smith_commit(
                        output_dir,
                        f"smith(nav-fix): {nav_fix['edited_paths'][0]}",
                        git=True,
                        # Stage ONLY shell.json. This runs before the LLM
                        # turn, so a blanket `git add -A` would sweep the
                        # user's in-progress work into a Smith commit
                        # (register SX-3) on a path they never invoked.
                        paths=list(nav_fix.get("edited_paths") or []),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("[smith-nav] commit failed — edit still on disk")
                await _persist_assistant_message(
                    project.id, nav_fix["message"], MessageType.chat,
                    metadata={
                        "intent": "SMITH_NAV_FIX",
                        "edited_paths": nav_fix["edited_paths"],
                    },
                )
                yield sse_event("message", {"text": nav_fix["message"]})
                return
            # Ambiguous nav ask → prepend menu structure to the memory
            # block so Smith can answer on turn 0 without a Read cycle.
            nav_block = render_nav_context_block(output_dir)
            if nav_block:
                memory_block = (
                    f"{nav_block}\n\n{memory_block}" if memory_block else nav_block
                )
    except Exception:  # noqa: BLE001
        logger.exception("[smith-nav] deterministic nav pass failed — falling through")

    # Run the loop off the event loop (the default SDK boundary blocks).
    # When FORGE_SMITH_ORCH=1 route through the orchestrator loop which
    # runs Smith → guards → retry until convergence (or rollback). The
    # orchestrator returns an OrchestratorResult; downstream code below
    # expects the classic `run_smith_agent` shape, so we adapt.
    try:
        from services.smith_chat_v2 import architect_flag_enabled as _arch_on_iter
        if _arch_on_iter():
            # New Smith-as-architect path (Migration Step 3 wire-up):
            # SmithSession → real seams → TurnResult verified against
            # git + guards. Bootstrap (no domain) still falls back to
            # the tactical stack — the ok_to_bootstrap branch below
            # catches TurnResult.status == "not_enabled" for that case.
            from services.smith_architect_wire import (
                run_iteration_via_architect,
                turn_result_to_legacy_dict,
            )
            _turn_result = await asyncio.to_thread(
                run_iteration_via_architect,
                message, output_dir, str(project.id) if project else "",
                memory_block,
            )
            logger.info(
                "[smith-arch] status=%s applied=%d",
                _turn_result.status, len(_turn_result.touched_paths),
            )
            if _turn_result.status == "not_enabled":
                # Fall back to the tactical orchestrator so bootstrap
                # keeps working while narrator-mode adapters ship.
                logger.info("[smith-arch] falling back to smith_orchestrator "
                            "(bootstrap / not-enabled)")
                from services.smith_orchestrator import run as _smith_orch_run
                orch = await asyncio.to_thread(
                    _smith_orch_run,
                    message, output_dir,
                    project_id=str(project.id) if project else None,
                )
                result = {
                    "answer":       orch.answer if orch.status in ("resolved", "no_op", "rolled_back") else None,
                    "question":     orch.question,
                    "handoff":      orch.handoff,
                    "diagnosis":    None,
                    "edited_paths": orch.applied_paths,
                    "trace":        orch.trace,
                }
            else:
                result = turn_result_to_legacy_dict(_turn_result)
                # Emit the smith_needs_user SSE event immediately if the
                # session returned needs_user — the frontend has a
                # dedicated NeedsUserCard renderer for it.
                _needs = result.pop("_needs_user", None)
                if _needs:
                    yield sse_event("smith_needs_user", _needs)
        elif os.environ.get("FORGE_SMITH_ORCH") == "1":
            from services.smith_orchestrator import run as _smith_orch_run
            orch = await asyncio.to_thread(
                _smith_orch_run,
                message, output_dir,
                project_id=str(project.id) if project else None,
            )
            # Adapt to the run_smith_agent-shaped dict the rest of this
            # handler expects (answer / question / handoff / edited_paths).
            result = {
                "answer":       orch.answer if orch.status in ("resolved", "no_op", "rolled_back") else None,
                "question":     orch.question,
                "handoff":      orch.handoff,
                "diagnosis":    None,
                "edited_paths": orch.applied_paths,
                "trace":        orch.trace,
            }
            logger.info("[smith-orch] status=%s turns=%d applied=%d commit=%s",
                        orch.status, orch.turns, len(orch.applied_paths), orch.commit)
        else:
            from agents.smith_agent import run_smith_agent

            # Phase 0 — hard intent classifier at ingress. When
            # confidence is high, we hand Smith a scoped tool subset.
            # When it's low (ambiguous ask), scoped_tools is None and
            # Smith uses the full 39-tool catalog exactly like before.
            # Gated on FORGE_SMITH_CLASSIFIER so we can dark-launch and
            # A/B test in prod without breaking existing users.
            scoped_tools = None
            classifier_meta: dict = {}
            if os.getenv("FORGE_SMITH_CLASSIFIER", "0") == "1":
                try:
                    from services.intent_classifier import classify_intent
                    intent_obj = await asyncio.to_thread(
                        classify_intent, message,
                    )
                    scoped_tools = intent_obj.tools
                    classifier_meta = {
                        "intent": intent_obj.intent,
                        "domain": intent_obj.domain,
                        "target": intent_obj.target,
                        "confidence": intent_obj.confidence,
                        "scoped": intent_obj.tools is not None,
                        "tool_count": (
                            len(intent_obj.tools)
                            if intent_obj.tools is not None else 0
                        ),
                    }
                    logger.info(
                        "[smith-classifier] intent=%s conf=%.2f scoped=%s tools=%d",
                        intent_obj.intent, intent_obj.confidence,
                        intent_obj.tools is not None,
                        len(intent_obj.tools or []),
                    )
                except Exception:
                    logger.exception("intent classifier failed — full catalog")

            # Live SSE stream of Smith's per-turn progress. Previously we
            # buffered reasoning chunks into a Python list and flushed them
            # only AFTER `run_smith_agent` returned — the user saw nothing
            # for the whole 1–3 minute run, and on a timeout got a canned
            # "took longer than expected" with zero context. The queue-plus-
            # heartbeat pattern below sends events the instant they land:
            #  - `reasoning` chunks from extended thinking
            #  - `tool_start` chips as Smith invokes each tool
            #  - `heartbeat` chips every ~12s of silence so the chat is
            #    never blank longer than that
            # A worker-thread callback pushes into `_smith_queue` via
            # `loop.call_soon_threadsafe` (thread-safe); the SSE generator
            # drains the queue in the main loop and yields each event.
            _smith_queue: asyncio.Queue = asyncio.Queue()
            _smith_loop = asyncio.get_running_loop()
            # Mutable holder so the progress callback (running in the worker
            # thread) can update the last-seen tool for heartbeat labelling
            # and timeout messages. Single-write from one thread is safe
            # under the GIL; no lock needed.
            _last_tool: dict = {"name": ""}

            def _reasoning_cb(text: str) -> None:  # noqa: ANN001
                if isinstance(text, str) and text.strip():
                    _smith_loop.call_soon_threadsafe(
                        _smith_queue.put_nowait,
                        {"kind": "reasoning", "text": text},
                    )

            def _progress_cb(evt: dict) -> None:  # noqa: ANN001
                if not isinstance(evt, dict):
                    return
                phase = str(evt.get("phase") or "")
                tool = str(evt.get("tool") or "")
                if phase == "tool_start" and tool:
                    _last_tool["name"] = tool
                _smith_loop.call_soon_threadsafe(
                    _smith_queue.put_nowait, evt,
                )

            # The SERVER's record that the previous turn ended asking the user
            # to confirm a destructive op. Without it, `_confirmed` was only
            # honoured when the model relayed the tool's summary verbatim, so
            # a paraphrase + "yes" left the op ungrantable forever
            # (register S24-8).
            _pending_confirmation = None
            try:
                from database import async_session as _async_session
                from services.smith_memory import load_pending_confirmation
                async with _async_session() as _sess:
                    _pending_confirmation = await load_pending_confirmation(
                        _sess, project.id,
                    )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[smith] could not read the pending confirmation — the "
                    "tool will ask again rather than act unconfirmed"
                )

            # Hard deadline on the whole Smith turn. The agent loop + its nested
            # sub-agents call the model with NO timeout anywhere, so a slow/stalled
            # Anthropic response used to hang the turn forever — the frontend
            # spinner never cleared ("Smith stops responding"). wait_for guarantees
            # the user always gets a response (the orphaned thread finishes on its
            # own). 180s default; a real turn is well under that.
            _smith_timeout = int(os.getenv("FORGE_SMITH_TIMEOUT_S", "180"))
            # Smith Auto-Act (recent_edits) — inject the per-project sliding
            # window into memory so resolve_target can echo it back and get
            # the +20 recency bias when the user asks about the same page
            # they just edited. Empty list → no line rendered.
            from services import smith_recent_edits as _sre
            _recent = _sre.get(project.id)
            _smith_memory = memory_block
            # PHASE-3: read-only brief awareness. When a design brief exists
            # on disk, prepend a one-line summary so Smith knows the palette,
            # display font, and density before proposing aesthetic edits.
            # No cost when no brief exists (silently skipped).
            try:
                from services.design_brief_editor import read_brief as _rb
                _b_for_mem = _rb(output_dir)
                if _b_for_mem is not None:
                    _brief_line = (
                        "<smith-design-brief>\n"
                        f"Current brief: {_b_for_mem.summary_line()}\n"
                        "For aesthetic asks (colors, fonts, density, feel), "
                        "use get_brief to read the full contract and edit_brief "
                        "to apply a partial patch.\n"
                        "</smith-design-brief>\n"
                    )
                    _smith_memory = _brief_line + (_smith_memory or "")
            except Exception:  # noqa: BLE001
                pass
            if _recent:
                _recent_line = (
                    "<smith-recent-edits>\n"
                    + "Recently edited routes (newest first): "
                    + ", ".join(_recent)
                    + "\nWhen calling resolve_target, pass these as recent_edits.\n"
                    + "</smith-recent-edits>\n"
                )
                _smith_memory = _recent_line + (_smith_memory or "")
            # Launch the smith worker as a Task instead of awaiting inline,
            # so this coroutine can interleave queue-drain yields between
            # tool calls. The 180s deadline is enforced by wall-clock check
            # in the drain loop (not by wait_for) — that way we can cancel
            # the worker AND still emit a final "stopped while working on X"
            # message with the last-seen tool.
            # Attachments the user put on THIS turn. Resolved here rather
            # than in the agent so the agent stays free of storage concerns
            # and remains injectable in tests.
            _attach_blocks = []
            if attachment_ids:
                try:
                    from services import chat_attachments
                    _attach_blocks = chat_attachments.load_blocks(
                        chat_attachments.attachments_root(),
                        str(project.id), list(attachment_ids))
                    logger.info("smith turn: %d attachment block(s)", len(_attach_blocks))
                except Exception as _e:  # noqa: BLE001 — never lose the turn
                    logger.warning("attachment load failed: %s", _e)

            _smith_worker = asyncio.create_task(asyncio.to_thread(
                run_smith_agent, message, output_dir, recall_block, _smith_memory,
                prior_messages=prior_messages,
                attachment_blocks=_attach_blocks,
                scoped_tools=scoped_tools,
                reasoning_callback=_reasoning_cb,
                progress_callback=_progress_cb,
                pending_confirmation=_pending_confirmation,
                current_route=current_route,
            ))
            _smith_started_at = time.monotonic()
            _smith_deadline = _smith_started_at + _smith_timeout
            _HEARTBEAT_SECONDS = 12.0
            _reasoning_chunks_seen: list[str] = []

            async def _drain_next_smith_event() -> None:
                """Yield one queued event (or a heartbeat if quiet).
                Wrapped in a helper only so the outer generator's flow is
                readable — the actual yields happen in the caller's loop.
                (Kept as a marker for future refactors; body inlined below.)
                """
                # NB: intentionally not an async gen; wired inline for `yield`.
                pass

            def _forward_evt_payload(evt: dict) -> "dict | None":
                """Translate a raw queue event into the smith_thought SSE
                payload the frontend expects. Returns None to drop."""
                if not isinstance(evt, dict):
                    return None
                kind = str(evt.get("kind") or "")
                phase = str(evt.get("phase") or "")
                if kind == "reasoning":
                    txt = str(evt.get("text") or "")
                    if not txt.strip():
                        return None
                    _reasoning_chunks_seen.append(txt)
                    return {"kind": "reasoning", "text": txt}
                if phase == "tool_start":
                    tool = str(evt.get("tool") or "")
                    if not tool:
                        return None
                    return {
                        "kind": "tool_start",
                        "tool": tool,
                        "args": evt.get("args") or {},
                    }
                return None

            try:
                while True:
                    if _smith_worker.done():
                        break
                    now = time.monotonic()
                    remaining_to_deadline = _smith_deadline - now
                    if remaining_to_deadline <= 0:
                        _smith_worker.cancel()
                        raise asyncio.TimeoutError()
                    wait_budget = min(_HEARTBEAT_SECONDS, remaining_to_deadline)
                    # Race the queue against worker completion so a fast
                    # worker (typical of test fixtures / short asks) doesn't
                    # trigger a spurious heartbeat while `wait_for` blocks
                    # on an empty queue for the full budget. `asyncio.wait`
                    # returns the moment EITHER the queue delivers or the
                    # worker task finishes — whichever comes first.
                    _q_task = asyncio.ensure_future(_smith_queue.get())
                    done, _pending = await asyncio.wait(
                        {_q_task, _smith_worker},
                        timeout=wait_budget,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if _q_task in done:
                        evt = _q_task.result()
                        payload = _forward_evt_payload(evt)
                        if payload is not None:
                            yield sse_event("smith_thought", payload)
                    else:
                        # Queue didn't deliver — cancel the pending get()
                        # so it doesn't dangle. Safe: nothing consumes its
                        # result on this branch.
                        _q_task.cancel()
                        # Heartbeat ONLY if the worker is still running.
                        # If it's done we'll break at the top of the next
                        # iteration and drain the tail; a heartbeat right
                        # before the answer chip would read as noise.
                        if not _smith_worker.done():
                            elapsed_s = int(time.monotonic() - _smith_started_at)
                            yield sse_event("smith_thought", {
                                "kind": "heartbeat",
                                "elapsed_s": elapsed_s,
                                "last_tool": _last_tool["name"],
                            })
                # Drain any tail events queued after the worker completed
                # but before we noticed. Bounded — the queue is fed only
                # by the worker (now done) and holds at most a few chunks.
                while True:
                    try:
                        evt = _smith_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    payload = _forward_evt_payload(evt)
                    if payload is not None:
                        yield sse_event("smith_thought", payload)

                # Surface any exception raised inside the worker (LLM
                # timeout upstream, tool crash, etc). This re-raises into
                # the outer `except Exception as e:` below.
                result = _smith_worker.result()
            except asyncio.CancelledError:
                # Deadline path — re-raise as TimeoutError so the existing
                # timeout branch handles the user-facing message.
                raise asyncio.TimeoutError()

            if classifier_meta and isinstance(result, dict):
                result.setdefault("classifier", classifier_meta)
            # Reasoning was streamed live from the queue; suppress the
            # post-hoc chunk-emit loop below to avoid duplicates.
            if isinstance(result, dict):
                result["_reasoning_chunks_streamed"] = True
    except (asyncio.TimeoutError, TimeoutError):
        _last = ""
        try:
            _last = _last_tool.get("name") or ""
        except Exception:  # noqa: BLE001
            pass
        logger.warning("[smith] turn timed out (last tool=%s)", _last)
        if _last:
            msg = (
                f"I stopped while still working on `{_last}` — that step ran long "
                f"and I wanted to keep the chat responsive. Please try again, and "
                f"if it's a big change, splitting it into smaller steps helps me "
                f"land it reliably."
            )
        else:
            msg = (
                "That one took longer than I expected, so I stopped to keep the chat "
                "responsive. Please try again — if it's a big change, splitting it into "
                "smaller steps helps me land it reliably."
            )
        await _persist_assistant_message(
            project.id, msg, MessageType.chat,
            metadata={"intent": "SMITH", "smith_error": "timeout", "last_tool": _last},
        )
        yield sse_event("message", {"text": msg})
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("[smith] agent loop failed")
        # Keep the user-facing note friendly, but surface a short hint of the real
        # cause instead of a blanket apology (the full error is in metadata + logs).
        _hint = type(e).__name__
        msg = (
            f"I hit a problem working on that ({_hint}). Could you rephrase, or try "
            f"a smaller step? I've logged the details."
        )
        await _persist_assistant_message(
            project.id, msg, MessageType.chat,
            metadata={"intent": "SMITH", "smith_error": str(e)[:400]},
        )
        yield sse_event("message", {"text": msg})
        return

    diagnosis    = result.get("diagnosis")    if isinstance(result, dict) else None
    answer       = result.get("answer")       if isinstance(result, dict) else None
    question     = result.get("question")     if isinstance(result, dict) else None
    handoff      = result.get("handoff")      if isinstance(result, dict) else None
    trace        = result.get("trace")        if isinstance(result, dict) else []
    edited_paths = result.get("edited_paths") if isinstance(result, dict) else []

    # ---- Phase 2 — auto-generate gate telemetry -----------------------
    # Runs the pure decider on best-effort signals. Currently EMIT-ONLY
    # (SSE `smith_auto_gate` event) so we can observe when the gate
    # would fire in prod BEFORE wiring the actual pipeline kickoff.
    # Enabling the real kickoff needs prevent-concurrent-generation
    # state we don't have in this scope — spec'd for a follow-up commit.
    if os.getenv("FORGE_SMITH_AUTO_GATE", "0") == "1":
        try:
            from services.auto_generate_gate import Signals, decide
            from services.patch_history import get_last_patch
            # Map classifier intent to auto-gate user_intent language.
            _intent = ""
            if classifier_meta:
                _intent = str(classifier_meta.get("intent") or "")
            _gate_user_intent = "edit"
            if _intent == "deploy":
                _gate_user_intent = "explicit_build"
            elif message.strip().lower().startswith(("bye", "thanks", "that's all", "thats all")):
                _gate_user_intent = "farewell"
            # Seconds since the last commit in the project repo.
            _secs_since_edit = 0.0
            try:
                last = get_last_patch(output_dir)
                if last.get("ok"):
                    import subprocess
                    p = subprocess.run(
                        ["git", "log", "-1", "--pretty=format:%at", last["sha"]],
                        cwd=output_dir, capture_output=True, text=True, timeout=5,
                    )
                    if p.returncode == 0 and p.stdout.strip().isdigit():
                        _secs_since_edit = max(0.0, time.time() - int(p.stdout.strip()))
            except Exception:
                pass
            # pending_confirmation — any trace entry with a
            # needs_confirmation-shaped result summary.
            _pending = any(
                "needs_confirmation" in str((s or {}).get("result_summary") or "")
                for s in (trace or [])
            )
            _decision = decide(Signals(
                user_intent=_gate_user_intent,
                seconds_since_edit=_secs_since_edit,
                pending_confirmation=_pending,
            ))
            logger.info(
                "[smith-auto-gate] intent=%s secs_edit=%.0f trigger=%s reason=%s",
                _gate_user_intent, _secs_since_edit,
                _decision.get("trigger"), _decision.get("reason"),
            )
            yield sse_event("smith_auto_gate", _decision)
        except Exception:
            logger.exception("smith_auto_gate: emission failed")

    # Claude-Code-style direct edits — Smith wrote files inside the loop.
    # Commit under one message so the change is visible in `git log`
    # alongside seam-based fixes.
    #
    # Do NOT run apply_post_generate_fixes here. That guard suite was
    # built for auto-generation-time correction of an untrusted LLM
    # first-pass; on user-directed edits it's actively hostile — it
    # forces FK-named fields back to Select-with-optionsFrom even when
    # the user asks for FileUpload, forces "*Number" fields to
    # NumberInput even when the user asks for text-with-pattern, and so
    # on. The user's intent is the authority for direct edits; the
    # tool's own applier is responsible for any structural validation
    # it needs before writing. See checkpoint 'dday' for the design
    # rationale.
    if edited_paths:
        try:
            from services.fix_applier import _commit as _smith_commit
            summary = ", ".join(edited_paths[:3])
            if len(edited_paths) > 3:
                summary += f" (+{len(edited_paths) - 3} more)"
            _smith_commit(output_dir, f"smith(direct-edit): {summary}", git=True)
            logger.info(f"[smith] direct-edit commit: {len(edited_paths)} file(s)")
        except Exception:  # noqa: BLE001
            logger.exception("[smith] failed to commit direct edits")
        # Smith Auto-Act (recent_edits) — remember which routes were just
        # touched so the NEXT turn's resolve_target scoring gets the +20
        # recency bias. Best-effort; never blocks the response.
        try:
            from services import smith_recent_edits as _sre_rec
            _sre_rec.record_edit(project.id, edited_paths)
        except Exception:  # noqa: BLE001
            logger.exception("[smith] failed to record recent edits")

    # Reasoning chunks — previously batched and emitted post-hoc so users
    # saw them ~seconds late. Now streamed live via `_smith_queue` above
    # (see `_forward_evt_payload`). This post-hoc loop stays as a fallback
    # only for code paths that DIDN'T go through the new streaming
    # branch (e.g. if a future refactor bypasses the queue) — in the
    # normal path `_reasoning_chunks_streamed` is set and this is skipped.
    _reasoning_chunks: list = []
    if isinstance(result, dict) and not result.get("_reasoning_chunks_streamed"):
        _reasoning_chunks = list(result.get("reasoning_chunks") or [])
    for chunk in _reasoning_chunks:
        if not isinstance(chunk, str) or not chunk.strip():
            continue
        yield sse_event("smith_thought", {
            "kind": "reasoning",
            "text": chunk,
        })

    # Stream one smith_thought event per tool call so the UI can render a
    # compact "Thinking…" chip above the final response.
    for step in trace or []:
        tool = step.get("tool") if isinstance(step, dict) else None
        if not tool or tool in ("propose_fix", "answer", "ask_user",
                                 "handoff_to_pipeline"):
            # Terminals are represented by the actual terminal event below —
            # don't double-render them as thoughts.
            continue
        yield sse_event("smith_thought", {
            "tool": tool,
            "summary": (step.get("result_summary") or "")[:280],
        })
        # Sub-agent trace expansion (slice 3) — when Smith invoked a
        # nested agent (e.g. _tool_app_modifier), stream each inner
        # tool call as its own chip prefixed with `↳` so the user sees
        # the Read/Bash/Edit sequence, not just the outer wrapper.
        for _sub in (step.get("sub_trace") or []):
            _s_tool = (_sub or {}).get("tool") or "?"
            yield sse_event("smith_thought", {
                "tool": f"↳ {_s_tool}",
                "summary": ((_sub or {}).get("summary") or "")[:280],
            })

    # ---- terminal: handoff_to_pipeline -----------------------------------
    if handoff and isinstance(deferred, dict):
        # Smith decided this turn belongs to the existing pipeline
        # (discovery / planner / refiner). Signal the outer router via
        # the shared deferred dict; emit a short narration so the user
        # sees Smith acknowledged the handoff before pipeline events
        # start streaming.
        kind = handoff.get("kind")
        narration = {
            "discovery": "Let me research this domain — kicking off discovery…",
            "planner":   "Drafting the plan now…",
            "refine":    "This needs a broader change than my seams cover — handing off to the code refiner…",
        }.get(kind, "Handing off to the pipeline…")
        # Persist Smith's narration so the chat history shows it too.
        await _persist_assistant_message(
            project.id, narration, MessageType.chat,
            metadata={
                "intent": "SMITH",
                "smith_trace": trace,
                "smith_handoff": handoff,
                "smith_elapsed_ms": _elapsed_ms(_t0),
            },
        )
        yield sse_event("message", {"text": narration})
        deferred["handoff"] = handoff
        return

    # ---- terminal: propose_fix -------------------------------------------
    if diagnosis:
        changes = _preview_fix_changes(output_dir, diagnosis)
        explanation = diagnosis.get("explanation") or (
            "I found the likely cause and can fix it."
        )
        metadata = _pending_fix_metadata(diagnosis, mode="smith")
        metadata["smith_trace"] = trace
        metadata["smith_elapsed_ms"] = _elapsed_ms(_t0)
        if edited_paths:
            metadata["edited_paths"] = list(edited_paths)
        await _persist_assistant_message(
            project.id, explanation, MessageType.chat, metadata=metadata,
        )
        yield fix_proposal_event(diagnosis, changes)
        yield sse_event("message", {"text": _normalize_proposal_text(explanation)})
        return

    # A tool asked the user to confirm a destructive op this turn. Record it
    # on the assistant message so the NEXT turn can honour a "yes" regardless
    # of whether the model relayed the prompt verbatim (register S24-8).
    from agents.smith_agent import _pending_confirmation_from
    _pending_conf = _pending_confirmation_from(trace)

    # Smith Auto-Act (S3/S4) — harvest resolve_target results from the
    # trace into UI metadata. `harvest_metadata` returns
    # {also_applies_to?, disambiguation?} — either key is absent when
    # not applicable, so this is safe to merge into every terminal.
    from services.smith_decide import (
        harvest_metadata as _harvest_auto_act,
        harvest_brief_metadata as _harvest_brief,
    )
    _auto_act_md = _harvest_auto_act(trace)
    _brief_md = _harvest_brief(trace)

    # ---- terminal: answer ------------------------------------------------
    if answer:
        _md = {
            "intent": "SMITH",
            "smith_trace": trace,
            "smith_elapsed_ms": _elapsed_ms(_t0),
        }
        if _pending_conf:
            _md["pending_confirmation"] = _pending_conf
        # CTX-1: persist paths Smith actually wrote so the NEXT turn's
        # memory block carries a focal resource-slice for the last-touched
        # route. Without this, a follow-up like "the button doesn't work"
        # sees no artifact anchor and Smith falls into the ask-user branch.
        if edited_paths:
            _md["edited_paths"] = list(edited_paths)
        # Only carry also_applies_to onto answer terminals — after a
        # successful edit. Disambiguation belongs on ask_user (Smith
        # is punting because resolve_target said chip).
        if _auto_act_md.get("also_applies_to"):
            _md["also_applies_to"] = _auto_act_md["also_applies_to"]
        # PHASE-3: attach brief_edit / brief_snapshot so DesignBriefCard
        # renders inline in the chat with the after-summary + tweaks.
        if _brief_md.get("brief_edit"):
            _md["brief_edit"] = _brief_md["brief_edit"]
        elif _brief_md.get("brief_snapshot"):
            _md["brief_snapshot"] = _brief_md["brief_snapshot"]
        await _persist_assistant_message(
            project.id, answer, MessageType.chat, metadata=_md,
        )
        yield sse_event("message", {"text": answer})
        return

    # ---- terminal: ask_user (or forced) ----------------------------------
    clarify = question or (
        "I couldn't pin that down. Could you tell me the specific screen or "
        "component you'd like me to work on?"
    )
    _md = {
        "intent": "SMITH",
        "smith_trace": trace,
        "smith_elapsed_ms": _elapsed_ms(_t0),
    }
    if _pending_conf:
        _md["pending_confirmation"] = _pending_conf
    if edited_paths:
        _md["edited_paths"] = list(edited_paths)
    # A chip-mode resolution rides on ask_user — Smith punted because the
    # candidates were near-equal; the disambiguation card gives the user
    # a one-click way to pick without retyping.
    if _auto_act_md.get("disambiguation"):
        _md["disambiguation"] = _auto_act_md["disambiguation"]
    await _persist_assistant_message(
        project.id, clarify, MessageType.chat, metadata=_md,
    )
    yield sse_event("message", {"text": clarify})


async def _handle_fix_proposal(project: Project, symptom: str):
    """FIX intent → recall + diagnose → stream a proposal (or a clarifying
    question when confidence is too low) and stash the Diagnosis. Async
    generator of SSE events; persists the assistant turn.

    Context-aware: when a pending_fix is already stashed from a prior turn we
    (a) treat an affirmative-apply message ("yes / fix it / apply / go ahead")
        as [APPLY_FIX] instead of re-diagnosing, and
    (b) fall back to re-emitting the existing proposal if the fresh diagnosis
        comes back low-confidence — never silently drop a good proposal.
    """
    output_dir = project.output_dir
    pending = await _load_pending_fix(project.id)
    _t0 = time.monotonic()  # A/B log: propose-turn elapsed

    # (a) User consenting to apply an outstanding proposal → route to apply.
    if pending and _looks_like_apply_intent(symptom):
        async for _ev in _handle_apply_fix(project):
            yield _ev
        return

    yield sse_event("status", {"message": "Diagnosing the issue..."})

    # Recall (on-disk dossier + registry; DB overlay is best-effort and degrades
    # silently against an async session, so we keep it DB-free here).
    recall = None
    resource_ctx = ""
    try:
        from services.app_recall import assemble_recall
        recall = assemble_recall(output_dir)
    except Exception:  # noqa: BLE001
        logger.exception("[fix] assemble_recall failed")
    try:
        from services.resource_registry_context import build_resource_context
        resource_ctx = build_resource_context(output_dir)
    except Exception:  # noqa: BLE001
        logger.exception("[fix] build_resource_context failed")

    # (Slice 3) Agentic reasoning loop — behind FORGE_FIX_AGENT. Same events,
    # same [APPLY_FIX] chip, same deterministic seams. The pending-fix +
    # apply-intent short-circuit above already ran, so the agent never
    # re-invents that context awareness.
    if _fix_agent_enabled():
        async for _ev in _handle_fix_proposal_agent(
            project, symptom, pending, recall, output_dir,
        ):
            yield _ev
        return

    # Diagnose (the diagnoser's default seam calls the real model; run it off the
    # event loop since it does blocking network I/O).
    try:
        from agents.fix_diagnoser import diagnose
        diagnosis = await asyncio.to_thread(
            diagnose, symptom, output_dir, recall=recall, resource_ctx=resource_ctx,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("[fix] diagnose failed")
        msg = "I hit an error while diagnosing that. Could you describe the exact screen and what you clicked?"
        await _persist_assistant_message(
            project.id, msg, MessageType.chat,
            metadata={"intent": "FIX", "fix_ab": build_error_entry(
                mode="single_shot", symptom=symptom, elapsed_ms=_elapsed_ms(_t0),
            )},
        )
        yield sse_event("message", {"text": msg})
        return

    confidence = 0.0
    try:
        confidence = float(diagnosis.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    artifact_path = (diagnosis.get("artifact") or {}).get("path")

    # Low confidence / nothing localized → normally ask a clarifying question.
    # BUT if we have a pending proposal from a prior turn, don't lose it — re-emit
    # it (the user probably provided extra context that didn't change the fix).
    if confidence < _FIX_MIN_CONFIDENCE or not artifact_path:
        if pending:
            changes = _preview_fix_changes(output_dir, pending)
            explanation = (pending.get("explanation") or
                           "Here's the fix I proposed. Click Apply to confirm.")
            metadata = _pending_fix_metadata(pending, mode="single_shot")
            metadata["fix_ab"] = build_propose_entry(
                mode="single_shot", symptom=symptom, diagnosis=pending,
                elapsed_ms=_elapsed_ms(_t0), phase="reemit",
            )
            await _persist_assistant_message(
                project.id, explanation, MessageType.chat, metadata=metadata,
            )
            yield fix_proposal_event(pending, changes)
            yield sse_event("message", {"text": _normalize_proposal_text(explanation)})
            return
        clarify = diagnosis.get("explanation") or (
            "I couldn't pin that down to a specific screen or workflow. "
            "Could you tell me which page you were on and the exact error you saw?"
        )
        await _persist_assistant_message(
            project.id, clarify, MessageType.chat,
            metadata={"intent": "FIX", "fix_ab": build_clarify_entry(
                mode="single_shot", symptom=symptom, elapsed_ms=_elapsed_ms(_t0),
            )},
        )
        yield sse_event("message", {"text": clarify})
        return

    # Confident proposal → stash the Diagnosis + stream the proposal + chip.
    changes = _preview_fix_changes(output_dir, diagnosis)
    explanation = diagnosis.get("explanation") or "I found the likely cause and can fix it."

    metadata = _pending_fix_metadata(diagnosis, mode="single_shot")
    metadata["fix_ab"] = build_propose_entry(
        mode="single_shot", symptom=symptom, diagnosis=diagnosis,
        elapsed_ms=_elapsed_ms(_t0),
    )
    await _persist_assistant_message(
        project.id, explanation, MessageType.chat, metadata=metadata,
    )
    yield fix_proposal_event(diagnosis, changes)
    yield sse_event("message", {"text": _normalize_proposal_text(explanation)})


async def _handle_apply_fix(project: Project):
    """`[APPLY_FIX]` → retrieve the stashed Diagnosis → apply via its
    deterministic seam → stream `fix_applied` + a narration. Async generator of
    SSE events; persists the assistant turn and a Version on commit."""
    output_dir = project.output_dir
    _t0 = time.monotonic()

    diagnosis = await _load_pending_fix(project.id)
    if not diagnosis:
        msg = ("I don't have a pending fix to apply. Describe the problem again "
               "and I'll diagnose it first.")
        await _persist_assistant_message(project.id, msg, MessageType.chat, metadata={"intent": "FIX"})
        yield sse_event("message", {"text": msg})
        return

    # A/B: attribute the applied entry to the mode that produced the pending fix.
    pending_mode = await _load_pending_fix_mode(project.id) or "unknown"

    yield sse_event("status", {"message": "Applying the fix..."})
    try:
        from services.fix_applier import apply_fix
        result = await asyncio.to_thread(apply_fix, output_dir, diagnosis, git=True)
    except Exception as e:  # noqa: BLE001
        logger.exception("[fix] apply_fix failed")
        await _clear_pending_fix(project.id)
        msg = f"I tried to apply the fix but hit an error: {_unwrap_error(e)}"
        await _persist_assistant_message(
            project.id, msg, MessageType.chat,
            metadata={"intent": "FIX", "fix_ab": build_applied_entry(
                mode=pending_mode, diagnosis=diagnosis, apply_result={"applied": False},
                elapsed_ms=_elapsed_ms(_t0),
            )},
        )
        yield sse_event("message", {"text": msg})
        return

    message = _narrate_fix_result(diagnosis, result)

    # Persist a Version record when a commit landed (parity with the UNDO path).
    if result.get("committed"):
        try:
            from services.git_service import git_get_head
            head = await git_get_head(output_dir)
            if head:
                await _persist_version(project.id, head, "fix: apply conversational fix")
        except Exception:  # noqa: BLE001
            logger.exception("[fix] version persist failed")

    verify_out = result.get("verify") or {}
    # Persist verify.remaining alongside resolved so Smith's cross-turn
    # memory (services.smith_memory) can surface a 'last apply left N
    # issues unresolved' line and continue on a follow-up "yes please"
    # instead of restarting cold. Keep the payload compact — just the
    # count is what Smith needs to act.
    remaining_raw = verify_out.get("remaining")
    remaining_list = list(remaining_raw) if isinstance(remaining_raw, list) else []
    await _persist_assistant_message(
        project.id, message, MessageType.chat,
        metadata={
            "intent": "FIX",
            "fixApplied": bool(result.get("applied")),
            "verify": {
                "resolved": bool(verify_out.get("resolved")),
                "remaining": remaining_list,
            },
            "fix_result": {
                "applied": bool(result.get("applied")),
                "resolved": bool(verify_out.get("resolved")),
                "committed": bool(result.get("committed")),
            },
            "fix_ab": build_applied_entry(
                mode=pending_mode, diagnosis=diagnosis, apply_result=result,
                elapsed_ms=_elapsed_ms(_t0),
            ),
        },
    )
    await _clear_pending_fix(project.id)

    yield fix_applied_event(result, message)
    yield sse_event("message", {"text": message})


def _narrate_fix_result(diagnosis: dict, result: dict) -> str:
    """Plain-language result of an apply for the end user."""
    verify = result.get("verify") or {}
    feature = (diagnosis or {}).get("feature") or "that feature"
    if result.get("applied") and verify.get("resolved"):
        return (f"Done — I applied the fix and re-checked it: {feature} should work now. "
                "You can undo this anytime.")
    if result.get("applied") and not verify.get("resolved"):
        remaining = verify.get("remaining") or []
        return ("I applied the change, but my re-check still sees an issue"
                + (f" ({len(remaining)} remaining)" if remaining else "")
                + ". Want me to take another look?")
    reason = result.get("reason")
    return ("I couldn't safely apply that fix"
            + (f": {reason}" if reason else "")
            + ". Could you confirm the screen and the exact error so I can re-diagnose?")


def _extract_plan_json(text: str) -> dict | None:
    """Extract plan JSON from ```plan-json ... ``` markers in text.

    Uses the robust multi-pass JSON extractor with 4 repair strategies.
    """
    from services.json_extractor import extract_json
    return extract_json(
        text,
        marker="```plan-json",
        expect_type=dict,
        required_fields=["module_name"],
    )


# ── Pending discovery (chat-approval pause/resume) ──────────────────────────
# Discovery output runs after [APPROVE_PLAN] but BEFORE the rest of the
# pipeline. The user reviews the dossier in chat, optionally edits the
# domain label / complianceNotes, then sends [APPROVE_DISCOVERY] to kick
# off the actual generation. While the dossier is awaiting approval it
# lives at `<output_dir>/.pending_discovery.json` — a file-based store
# is enough since the project dir is the natural project-scoped location
# (vs. polluting the conversations table for state that's transient).


def _pending_discovery_path(output_dir: str) -> Path:
    from pathlib import Path as _P
    return _P(output_dir) / ".pending_discovery.json"


def _save_pending_discovery(output_dir: str, discovery: dict) -> None:
    """Persist the discovery dossier to `.pending_discovery.json`. Creates
    parent dirs. Overwrites any previous pending file (intentional — a new
    discovery run supersedes the previous awaiting-approval one)."""
    p = _pending_discovery_path(output_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(discovery, indent=2, sort_keys=True))


def _load_pending_discovery(output_dir: str) -> dict | None:
    """Load the pending discovery dossier, or None if no pending file exists.
    Used by the chat handler to detect the awaiting-approval state."""
    p = _pending_discovery_path(output_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _clear_pending_discovery(output_dir: str) -> None:
    """Remove the pending discovery file. Called after the user approves
    and the pipeline begins (so a subsequent regen runs fresh discovery)."""
    p = _pending_discovery_path(output_dir)
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass


# Allowed top-level keys the user can edit in the approval message.
# Keeping this enum-style prevents stray fields from being applied and
# limits the blast radius of malformed edits.
_DISCOVERY_EDITABLE_KEYS = {"domain", "complianceNotes", "mode"}
"""Whitelist for the ``[APPROVE_DISCOVERY] {…}`` payload.

``mode`` (GP-1) carries the user's Fast/Complete generation-profile
choice. It's NOT applied to the discovery dossier (the discovery
approve/apply branch checks the whitelist just to know what to pull
off the message); it's read separately by :func:`_parse_generation_profile_id`
and persisted via :func:`services.generation_profile.persist_profile`."""


def _parse_discovery_edits(message: str) -> dict:
    """Extract any user edits embedded in the approval message.

    The frontend can send the approval signal with optional edits in JSON:
        [APPROVE_DISCOVERY] {"domain": "Hospitality", "complianceNotes": ["pci"]}

    Returns a dict of allowed key→value, ignoring any keys not in the
    editable whitelist. Returns {} for plain `[APPROVE_DISCOVERY]` with
    no JSON body.
    """
    # The signal is `[APPROVE_DISCOVERY]` (case-insensitive); everything
    # after the closing bracket (if it parses) is the edit payload.
    msg = message.strip()
    if not msg.upper().startswith("[APPROVE_DISCOVERY]"):
        return {}
    tail = msg[len("[APPROVE_DISCOVERY]"):].strip()
    if not tail:
        return {}
    # Try to parse as JSON; tolerate prose around the JSON object.
    import re as _re
    m = _re.search(r"\{[\s\S]*\}", tail)
    if not m:
        return {}
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {k: v for k, v in parsed.items() if k in _DISCOVERY_EDITABLE_KEYS}


def _apply_discovery_edits(discovery: dict, edits: dict) -> dict:
    """Return a NEW dict with user edits applied on top of the discovery
    dossier. Doesn't mutate the input. Edits are validated minimally —
    domain must be a non-empty string; complianceNotes must be a list of
    strings from the known regime enum."""
    if not edits:
        return dict(discovery)
    out = dict(discovery)
    if "domain" in edits and isinstance(edits["domain"], str) and edits["domain"].strip():
        out["domain"] = edits["domain"].strip()
    if "complianceNotes" in edits and isinstance(edits["complianceNotes"], list):
        # Re-use the discovery agent's enum coercion so invalid regimes
        # get dropped rather than smuggled in via the edit channel.
        from agents.domain_agent import _coerce_compliance
        out["complianceNotes"] = _coerce_compliance(edits["complianceNotes"])
    # NOTE: ``mode`` is intentionally NOT applied to the dossier — it's
    # a generation-profile signal read separately by the approve branch.
    return out


def _parse_generation_profile_id(message: str) -> str | None:
    """Extract the ``mode`` field from an ``[APPROVE_DISCOVERY] {…}`` payload.

    Returns the raw string (e.g. ``"fast"``, ``"complete"``) or None
    when the payload is missing / malformed. ``get_profile()`` handles
    unknown values downstream by falling back to the default."""
    msg = message.strip()
    if not msg.upper().startswith("[APPROVE_DISCOVERY]"):
        return None
    tail = msg[len("[APPROVE_DISCOVERY]"):].strip()
    if not tail:
        return None
    import re as _re
    m = _re.search(r"\{[\s\S]*\}", tail)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    mode = parsed.get("mode")
    return mode if isinstance(mode, str) and mode else None


async def _sync_pages_from_app_model(
    project_id: uuid.UUID,
    output_dir: str,
) -> None:
    """Create PageDefinition records from the pages array in app-model.json.

    Reads the generated app-model.json, and for each page entry that doesn't
    already exist in the DB (by route), creates a PageDefinition record.
    Also auto-generates navigation.json if it doesn't exist yet.
    """
    from models.page import PageDefinition

    app_model_path = Path(output_dir) / "app-model.json"
    if not app_model_path.exists():
        return

    try:
        app_model = json.loads(app_model_path.read_text())
    except (json.JSONDecodeError, OSError):
        return

    pages = app_model.get("pages", [])
    if not pages:
        return

    from database import async_session
    async with async_session() as sess:
        # Load existing routes to avoid duplicates
        result = await sess.execute(
            select(PageDefinition.route)
            .where(PageDefinition.project_id == project_id)
        )
        existing_routes = {r for (r,) in result.all()}

        for page in pages:
            route = page.get("path") or page.get("route", "/")
            if route in existing_routes:
                continue
            name = page.get("component") or page.get("name") or route
            sess.add(PageDefinition(
                project_id=project_id,
                name=name,
                route=route,
            ))
            existing_routes.add(route)

        await sess.commit()

    # Auto-generate navigation.json from pages if it doesn't exist yet
    nav_path = Path(output_dir) / "navigation.json"
    if not nav_path.exists():
        from routers.navigation import _build_nav_from_app_model
        _build_nav_from_app_model(output_dir)


def _sync_workflows_from_plan(output_dir: str, plan: dict | None) -> None:
    """Create workflow JSON files from the plan's workflows array.

    Generates enterprise-grade workflows using proper node types (trigger,
    condition, approval, assignment, ai_classify, etc.) — not just sequential
    action chains. Each step is mapped to the most appropriate node type based
    on keyword analysis.
    """
    if not plan:
        return

    workflows = plan.get("workflows", [])
    if not workflows:
        return

    wf_dir = Path(output_dir) / "workflows"
    wf_dir.mkdir(exist_ok=True)

    # PER-WORKFLOW skip, not all-or-nothing. Other writers (CRUD
    # scaffolds, archetype emitters) may populate workflows/ first;
    # their presence must not drop the plan's DOMAIN workflows. The old
    # `if any(*.json): return` did exactly that — fleet Phase-0 caught
    # banking shipping 21 CRUD files and 0 of its 8 plan workflows.
    def _fold_wf(s: str) -> str:
        return "".join(ch for ch in str(s).lower() if ch.isalnum())

    existing_wf: set[str] = set()
    for _p in wf_dir.glob("*.json"):
        existing_wf.add(_fold_wf(_p.stem))
        try:
            _doc = json.loads(_p.read_text(encoding="utf-8"))
            for _k in ("name", "id"):
                if _doc.get(_k):
                    existing_wf.add(_fold_wf(str(_doc[_k])))
        except Exception:  # noqa: BLE001 — unreadable file can't claim a name
            pass

    from services.workflow_step_translator import is_rich_step_list, translate_workflow
    from services.workflow_generator import (
        _wire_document_persist,
        _load_table_names,
        derive_trigger_contract,
    )

    models = {m.get("name", ""): m for m in (plan.get("data_models") or [])}
    table_names = _load_table_names(output_dir)

    # Same archetype-owned emitter hook as generate_workflow_definitions.
    # _sync_workflows_from_plan writes files BEFORE generate_workflow_definitions
    # runs, and generate_workflow_definitions skips already-executable files,
    # so without this hook here the archetype emitter never wins for names it
    # would fuzzy-match. Kept identical to the other callsite.
    archetype = (plan.get("archetype") or plan.get("app_archetype") or "").strip()
    try:
        from services.archetype_workflows import find_emitter as _find_archetype_emitter
    except Exception:  # pragma: no cover — module optional
        _find_archetype_emitter = None  # type: ignore[assignment]

    try:
        from services.resource_registry import build_canonical_registry as _build_reg
        _reg = _build_reg(plan)
    except Exception:
        _reg = None

    used_ids: set[str] = set()

    def _unique_id(candidate: str) -> str:
        base = candidate or str(uuid.uuid4())[:8]
        wid = base
        n = 2
        while wid in used_ids:
            wid = f"{base}-{n}"
            n += 1
        used_ids.add(wid)
        return wid

    for wf in workflows:
        name = wf.get("name", "Untitled")
        if _fold_wf(name) in existing_wf:
            continue  # already on disk (this run or a previous writer)
        existing_wf.add(_fold_wf(name))
        steps = wf.get("steps", [])

        # R1/R2: top-level event/schedule trigger contract for the runtime
        # event bus + cron scheduler. None (key absent) for manual workflows.
        try:
            _trig_contract = derive_trigger_contract(wf)
        except Exception:  # noqa: BLE001 — never block workflow sync
            _trig_contract = None

        # Archetype-owned emitter wins over the step translator for names the
        # archetype claims (fuzzy match — see services.archetype_workflows).
        _arch_def = None
        if _find_archetype_emitter is not None:
            _emitter = _find_archetype_emitter(archetype, name)
            if _emitter is not None:
                try:
                    _arch_def = _emitter(wf, plan, table_names, _reg)
                    if _arch_def is not None:
                        logger.info(
                            "[sync-wf] %s: using archetype-owned emitter for '%s'",
                            archetype, name,
                        )
                except Exception as _ae:
                    logger.warning(
                        "[sync-wf] archetype emitter for %s/%s failed (%s) — falling back",
                        archetype, name, _ae,
                    )
                    _arch_def = None

        if _arch_def is not None:
            wf_id = _unique_id(_arch_def.get("id") or str(uuid.uuid4())[:8])
            wf_data = {
                "id": wf_id,
                "name": name,
                "description": _arch_def.get("description") or wf.get("description", f"{name} workflow"),
                "processVariables": _arch_def.get("processVariables") or [],
                "definition": _arch_def["definition"],
            }
            # Skip persist-wiring for archetype-authored workflows — the emitter
            # controls the full node graph, no ai_extract→db_insert stitching
            # to do.
            if _trig_contract:
                wf_data["trigger"] = _trig_contract
            wf_path = wf_dir / f"{wf_id}.json"
            wf_path.write_text(json.dumps(wf_data, indent=2), encoding="utf-8")
            continue

        translated = translate_workflow(wf) if is_rich_step_list(steps) else None
        if translated is not None:
            wf_id = _unique_id(translated["id"] or str(uuid.uuid4())[:8])
            wf_data = {
                "id": wf_id,
                "name": name,
                "description": wf.get("description", f"{name} workflow"),
                # Launcher-supplied inputs ({{memberId}} etc.) are declared
                # here — dropping this key made every dispatch input an
                # undefined-ref for the workflow validator.
                "processVariables": translated.get("processVariables") or [],
                "definition": {
                    "trigger": translated["definition"]["trigger"],
                    "steps": steps,  # preserve raw steps for the editor/preview
                    "nodes": translated["definition"]["nodes"],
                    "edges": translated["definition"]["edges"],
                },
            }
            # Splice a db_insert after any ai_extract that has no persist step, so
            # extracted fields actually save. Idempotent; a workflow that already
            # persists is untouched. (generate_workflow_definitions SKIPS synced
            # executable workflows, so this is the only place it runs on them.)
            try:
                _wire_document_persist(wf_data, wf, models, table_names)
            except Exception as _pe:
                logger.warning("persist-wiring skipped for %s: %s", name, _pe)
        else:
            wf_id = str(uuid.uuid4())[:8]
            # Planner emits `trigger` as either a bare string ("form_submit")
            # or a dict ({"type": "form_submit"}). Downstream _map_trigger_type
            # calls .lower(), so coerce to a string here.
            _raw_trigger = wf.get("trigger", "manual")
            if isinstance(_raw_trigger, dict):
                trigger_str = str(_raw_trigger.get("type") or "manual")
            elif isinstance(_raw_trigger, str):
                trigger_str = _raw_trigger
            else:
                trigger_str = "manual"
            nodes, edges = _build_workflow_graph(wf_id, name, trigger_str, steps)
            from services.workflow_process_variables import (
                derive_process_variables as _derive_pv,
                strip_source as _strip_pv_source,
            )
            wf_data = {
                "id": wf_id,
                "name": name,
                "description": wf.get("description", f"{name} workflow"),
                "processVariables": _strip_pv_source(_derive_pv(wf, nodes)),
                "definition": {
                    "trigger": {"type": _map_trigger_type(trigger_str)},
                    "steps": steps,
                    "nodes": nodes,
                    "edges": edges,
                },
            }
        if _trig_contract:
            wf_data["trigger"] = _trig_contract
        (wf_dir / f"{wf_id}.json").write_text(json.dumps(wf_data, indent=2))

    logger.info(f"[workflows] Synced {len(workflows)} workflows from plan to {wf_dir}")

    # Auto-link pages to human-in-loop nodes
    _auto_link_pages_to_workflows(output_dir, plan)


def _auto_link_pages_to_workflows(output_dir: str, plan: dict | None) -> None:
    """Auto-link generated pages to human-in-loop workflow nodes.

    Reads pages from app-model.json and plan, matches them to assignment/approval/
    task_pool nodes in workflow JSON files by name similarity, and populates
    pageId/pageName in the node config.
    """
    # Collect available pages from app-model.json and plan
    pages: list[dict] = []

    app_model_path = Path(output_dir) / "app-model.json"
    if app_model_path.exists():
        try:
            app_model = json.loads(app_model_path.read_text())
            for p in app_model.get("pages", []):
                pages.append({
                    "id": p.get("id", p.get("route", "/")),
                    "name": p.get("component") or p.get("name") or p.get("route", "/"),
                    "route": p.get("path") or p.get("route", "/"),
                })
        except (json.JSONDecodeError, OSError):
            pass

    # Also extract page names from plan
    if plan:
        for p in plan.get("pages", []):
            name = p.get("name", "")
            route = p.get("route", "/")
            if name and not any(pg["name"] == name for pg in pages):
                pages.append({"id": route, "name": name, "route": route})

    if not pages:
        return

    # Build a lookup: lowercase keywords from page name → page
    def _page_keywords(page: dict) -> set[str]:
        name = page["name"].lower().replace("_", " ").replace("-", " ")
        return set(name.split())

    human_node_types = {"assignment", "approval", "task_pool"}

    wf_dir = Path(output_dir) / "workflows"
    if not wf_dir.exists():
        return

    modified = 0
    for wf_file in wf_dir.glob("*.json"):
        try:
            wf_data = json.loads(wf_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        nodes = wf_data.get("definition", {}).get("nodes", [])
        changed = False

        for node in nodes:
            data = node.get("data", {})
            node_type = data.get("nodeType", "")
            config = data.get("config", {})

            # Only link human-in-loop nodes that don't already have a page
            if node_type not in human_node_types:
                continue
            if config.get("pageId"):
                continue

            # Match by label similarity to page names
            label = data.get("label", "").lower().replace("_", " ").replace("-", " ")
            label_words = set(label.split())

            best_match = None
            best_score = 0

            for page in pages:
                page_words = _page_keywords(page)
                # Score: number of overlapping words
                overlap = len(label_words & page_words)
                if overlap > best_score:
                    best_score = overlap
                    best_match = page

            # Also try substring match if no word overlap
            if best_score == 0:
                for page in pages:
                    page_name_lower = page["name"].lower()
                    if label in page_name_lower or page_name_lower in label:
                        best_match = page
                        best_score = 1
                        break

            if best_match and best_score > 0:
                config["pageId"] = best_match["id"]
                config["pageName"] = best_match["name"]
                changed = True

        if changed:
            wf_file.write_text(json.dumps(wf_data, indent=2))
            modified += 1

    if modified:
        logger.info(f"[workflows] Auto-linked pages to nodes in {modified} workflow(s)")


def _map_trigger_type(trigger_str) -> str:
    """Map a plan trigger to a valid trigger type.

    Accepts str, dict{type: str}, or None — planner emits any of those
    depending on the run. Belt-and-suspenders defense; upstream callers
    should have already string-coerced but a bad plan shouldn't crash
    the whole pipeline."""
    if isinstance(trigger_str, dict):
        trigger_str = str(trigger_str.get("type") or "")
    elif trigger_str is None:
        trigger_str = ""
    else:
        trigger_str = str(trigger_str)
    t = trigger_str.lower()
    if any(w in t for w in ["schedule", "cron", "hourly", "daily", "weekly"]):
        return "schedule"
    if any(w in t for w in ["webhook", "http", "api"]):
        return "webhook"
    if any(w in t for w in ["db_change", "record", "insert", "update"]):
        return "db_change"
    if "manual" in t:
        return "manual"
    return "api_event"


def _infer_node_type(step_name: str) -> tuple[str, dict]:
    """Infer the best workflow node type and config from a step name.

    Returns (node_type, config_dict).
    Keyword lists are ordered so that more specific matches win first
    (e.g. "ai_generate" before generic "generate" which maps to db_query).
    """
    s = step_name.lower()

    # --- AI/ML nodes (match ONLY explicit AI-prefixed or unambiguous ML terms) ---
    if any(w in s for w in ["ai_classify", "ai_categorize", "auto_label", "auto_tag",
                            "sentiment", "detect_spam", "detect_fraud"]):
        return "ai_classify", {"aiInput": "{{previous.output}}", "aiLabels": [], "nodeType": "ai_classify"}
    if any(w in s for w in ["ai_extract", "ai_parse", "auto_extract", "ocr", "nlp_extract"]):
        return "ai_extract", {"aiInput": "{{previous.output}}", "aiExtractFields": [], "nodeType": "ai_extract"}
    if any(w in s for w in ["ai_decide", "ai_decision", "ai_evaluate", "ai_score", "ai_rank",
                            "ml_score", "predict"]):
        return "ai_decide", {"aiContext": "{{previous.output}}", "aiOptions": [], "nodeType": "ai_decide"}
    if any(w in s for w in ["ai_generate", "ai_compose", "ai_draft", "ai_summarize",
                            "personalize_message", "auto_draft", "auto_reply",
                            "compose", "draft", "summarize"]):
        return "ai_generate", {"aiPrompt": "", "aiTone": "professional", "nodeType": "ai_generate"}

    # --- Human-in-the-loop nodes ---
    if any(w in s for w in ["approve", "approval", "review", "sign_off",
                            "confirm", "authorize", "sign", "consent", "ratify"]):
        return "approval", {"approvalType": "single", "assignType": "role", "assignTarget": "Manager", "slaHours": 24, "nodeType": "approval"}
    if any(w in s for w in ["assign", "delegate", "route_to", "auto_assign",
                            "dispatch", "allocate", "forward", "hand_off", "handoff"]):
        return "assignment", {"assignType": "role", "assignTarget": "", "nodeType": "assignment"}
    if any(w in s for w in ["task_pool", "pool", "round_robin", "load_balance",
                            "distribute", "queue", "work_queue"]):
        return "task_pool", {"assignType": "group", "assignTarget": "", "slaHours": 24, "nodeType": "task_pool"}
    if any(w in s for w in ["escalat", "raise_priority", "bump", "urgent"]):
        return "escalation", {"escalateTo": "Manager", "slaHours": 4, "nodeType": "escalation"}

    # --- Flow control nodes ---
    if any(w in s for w in ["decision_table", "lookup_table", "rule_matrix",
                            "rule_table", "policy_table", "dmn"]):
        return "decision", {"decisionTable": {"columns": [], "rows": []}, "outputMapping": {}, "nodeType": "decision"}
    if any(w in s for w in ["check", "threshold", "validate", "verify", "filter",
                            "condition", "if_", "ensure", "require", "match",
                            "compare", "evaluate", "assess", "test", "gate"]):
        return "condition", {"expression": "", "nodeType": "condition"}
    if any(w in s for w in ["wait", "delay", "pause", "cooldown",
                            "timeout", "timer", "sleep", "hold"]):
        return "wait", {"duration": "1 hour", "nodeType": "wait"}

    # --- Action nodes (specific subtypes before fallback) ---
    config: dict = {"nodeType": "action"}

    # Email actions
    if any(w in s for w in ["email", "mail", "send_invoice", "send_receipt",
                            "send_confirmation", "send_welcome", "send_reset",
                            "send_reminder", "send_report"]):
        config["actionType"] = "send_email"
        return "action", config

    # Notification actions
    if any(w in s for w in ["notify", "alert", "notification", "remind",
                            "message", "ping", "warn", "announce", "broadcast",
                            "sms", "push_notification", "slack", "teams"]):
        config["actionType"] = "send_notification"
        return "action", config

    # HTTP / integration actions
    if any(w in s for w in ["http", "api_call", "webhook", "integrate",
                            "post_to", "upload", "download", "import", "export",
                            "sync", "refresh", "fetch_from", "call_api",
                            "rest", "graphql", "soap"]):
        config["actionType"] = "http_call"
        return "action", config

    # Database actions (broadened — most CRUD / data operations)
    if any(w in s for w in ["query", "db", "database", "create", "update",
                            "insert", "save", "store", "record", "log",
                            "delete", "remove", "archive", "submit", "persist",
                            "write", "set_status", "change_status", "mark_as",
                            "increment", "decrement", "upsert", "bulk",
                            "process", "calculate", "compute", "transform",
                            "generate", "close", "open", "cancel", "complete",
                            "activate", "deactivate", "enable", "disable",
                            "publish", "unpublish", "schedule", "register",
                            "enroll", "apply", "reject", "accept", "deny",
                            "refund", "charge", "pay", "bill", "invoice"]):
        config["actionType"] = "db_query"
        return "action", config

    # Fallback — truly unknown steps
    config["actionType"] = "custom"
    return "action", config


def _build_workflow_graph(
    wf_id: str, name: str, trigger_str: str, steps: list,
) -> tuple[list[dict], list[dict]]:
    """Build a rich workflow graph with proper node types and branching.

    Produces nodes and edges lists for the workflow definition.
    Inserts condition nodes where appropriate to create branching logic.
    """
    # Normalize steps into list of dicts with {name, node_type, action}
    normalized_steps: list[dict] = []
    for s in steps:
        if isinstance(s, dict):
            normalized_steps.append({
                "name": s.get("name") or s.get("action") or "step",
                "node_type": s.get("node_type", ""),
                "action": s.get("action", ""),
            })
        else:
            normalized_steps.append({"name": str(s), "node_type": "", "action": ""})
    steps = normalized_steps

    # Map action subtypes to their parent node type
    _ACTION_SUBTYPES = {"db_query", "send_email", "send_notification", "http_call", "custom"}

    nodes: list[dict] = []
    edges: list[dict] = []
    dangling_branch_ids: list[str] = []  # branch nodes that need connecting to End
    x_main = 300
    x_branch = 600
    y = 50
    y_step = 120
    node_counter = 0

    def make_id() -> str:
        nonlocal node_counter
        node_counter += 1
        return f"n_{wf_id}_{node_counter}"

    def add_node(ntype: str, label: str, config: dict, x: int = x_main) -> str:
        nonlocal y
        nid = make_id()
        config.setdefault("nodeType", ntype)
        nodes.append({
            "id": nid,
            "type": ntype,
            "position": {"x": x, "y": y},
            "data": {"label": label, "nodeType": ntype, "config": config, "status": "idle"},
        })
        y += y_step
        return nid

    def add_edge(src: str, tgt: str, etype: str = "default", label: str | None = None) -> None:
        edge: dict = {"id": f"e_{src}_{tgt}", "source": src, "target": tgt}
        data: dict = {"edgeType": etype}
        if label:
            data["label"] = label
        edge["data"] = data
        # Else edges must use the bottom handle (id="else") on the source node
        if etype == "else":
            edge["sourceHandle"] = "else"
        edges.append(edge)

    # 1. Trigger node
    trigger_type = _map_trigger_type(trigger_str)
    trigger_config: dict = {"type": trigger_type, "nodeType": "trigger"}
    if trigger_type == "schedule":
        trigger_config["cron"] = "0 * * * *" if "hourly" in trigger_str.lower() else "0 0 * * *"
    elif trigger_type == "webhook":
        trigger_config["path"] = f"/webhooks/{name.lower().replace(' ', '-')}"
    elif trigger_type == "api_event":
        trigger_config["event"] = trigger_str

    trigger_id = add_node("trigger", trigger_str.replace("_", " ").title(), trigger_config)

    def _resolve_step(step_dict: dict) -> tuple[str, str, dict]:
        """Resolve a step dict to (node_type, label, config).

        Uses explicit node_type if provided, falls back to keyword inference.
        """
        step_name = step_dict["name"]
        explicit_type = step_dict.get("node_type", "").strip()
        action_desc = step_dict.get("action", "")
        label = step_name.replace("_", " ").title()

        if explicit_type:
            # Use explicit type — map action subtypes to "action" node type
            if explicit_type in _ACTION_SUBTYPES:
                config = {"actionType": explicit_type, "nodeType": "action", "description": action_desc}
                return "action", label, config
            else:
                config = {"nodeType": explicit_type, "description": action_desc}
                return explicit_type, label, config
        else:
            # Fallback to keyword inference for legacy steps
            ntype, config = _infer_node_type(step_name)
            if action_desc:
                config["description"] = action_desc
            return ntype, label, config

    prev_id = trigger_id
    i = 0
    while i < len(steps):
        ntype, label, config = _resolve_step(steps[i])

        # For condition/check nodes: create a branch
        if ntype == "condition":
            cond_id = add_node("condition", label, config)
            add_edge(prev_id, cond_id)

            # "Then" branch — next step
            if i + 1 < len(steps):
                next_type, next_label, next_config = _resolve_step(steps[i + 1])
                then_id = add_node(next_type, next_label, next_config)
                add_edge(cond_id, then_id, "then", "Yes")
                prev_id = then_id
                i += 2
            else:
                prev_id = cond_id
                i += 1

            # "Else" branch — notification, connects to End later
            save_y = y
            else_id = add_node("action", "Log Skipped", {
                "actionType": "send_notification", "nodeType": "action",
                "description": f"Skipped: {label} condition not met",
            }, x=x_branch)
            add_edge(cond_id, else_id, "else", "No")
            dangling_branch_ids.append(else_id)
            y = save_y
            continue

        # For decision table nodes: create branches (match/no-match)
        if ntype == "decision":
            decide_id = add_node("decision", label, config)
            add_edge(prev_id, decide_id)

            if i + 1 < len(steps):
                next_type, next_label, next_config = _resolve_step(steps[i + 1])
                then_id = add_node(next_type, next_label, next_config)
                add_edge(decide_id, then_id, "then", "Match")
                prev_id = then_id
                i += 2
            else:
                prev_id = decide_id
                i += 1

            save_y = y
            else_id = add_node("action", "No Match Fallback", {
                "actionType": "send_notification", "nodeType": "action",
                "description": f"No matching rule in: {label}",
            }, x=x_branch)
            add_edge(decide_id, else_id, "else", "No Match")
            dangling_branch_ids.append(else_id)
            y = save_y
            continue

        # For AI decide nodes: create branches (high/low confidence)
        if ntype == "ai_decide":
            decide_id = add_node("ai_decide", label, config)
            add_edge(prev_id, decide_id)

            if i + 1 < len(steps):
                next_type, next_label, next_config = _resolve_step(steps[i + 1])
                then_id = add_node(next_type, next_label, next_config)
                add_edge(decide_id, then_id, "then", "High")
                prev_id = then_id
                i += 2
            else:
                prev_id = decide_id
                i += 1

            save_y = y
            else_id = add_node("action", "Flag For Review", {
                "actionType": "send_notification", "nodeType": "action",
                "description": f"Low confidence: {label} needs manual review",
            }, x=x_branch)
            add_edge(decide_id, else_id, "else", "Low")
            dangling_branch_ids.append(else_id)
            y = save_y
            continue

        # Standard sequential node
        node_id = add_node(ntype, label, config)
        add_edge(prev_id, node_id)
        prev_id = node_id
        i += 1

    # End node
    end_id = add_node("end", "Complete", {"nodeType": "end"})
    add_edge(prev_id, end_id)

    # Connect all dangling branch nodes to End
    for branch_id in dangling_branch_ids:
        add_edge(branch_id, end_id)

    return nodes, edges


def _generate_schema_from_plan(output_dir: str, plan: dict | None) -> None:
    """Generate src/db/schema.ts from plan's data_models if it doesn't already exist.

    The Figma design-to-code agent focuses on UI and may skip DB schema generation.
    This ensures the schema file is created from the plan's data_models so the
    generated app has proper Drizzle ORM models.
    """
    if not plan:
        return
    data_models = plan.get("data_models", [])
    if not data_models:
        return

    schema_path = Path(output_dir) / "src" / "db" / "schema.ts"
    if schema_path.exists():
        return  # Already generated by the agent
    # The schema agent's per-entity dir is the authoritative source. Writing a
    # singular schema.ts alongside it shadows the dir for `@/db/schema` imports
    # (workflows then hit "unknown table"). Never create the shadow if the dir exists.
    if (schema_path.parent / "schema").is_dir():
        return

    # Ensure directory exists
    schema_path.parent.mkdir(parents=True, exist_ok=True)

    # Map plan types to Drizzle types
    type_map = {
        "serial": "serial",
        "uuid": "uuid",
        "varchar": "varchar",
        "text": "text",
        "integer": "integer",
        "int": "integer",
        "boolean": "boolean",
        "timestamp": "timestamp",
        "jsonb": "jsonb",
        "json": "jsonb",
        "numeric": "numeric",
        "real": "real",
        "date": "date",
    }

    imports = set()
    imports.add("pgTable")
    table_code_blocks = []

    for model in data_models:
        table_name = model.get("name", "unknown")
        # Convert PascalCase to snake_case for table name
        snake_name = ""
        for i, ch in enumerate(table_name):
            if ch.isupper() and i > 0:
                snake_name += "_"
            snake_name += ch.lower()

        fields = model.get("fields", [])
        field_lines = []
        for field in fields:
            fname = field.get("name", "")
            ftype_raw = field.get("type", "text").lower()
            is_pk = field.get("primaryKey", False)
            nullable = field.get("nullable", True)

            # Parse type — handle varchar(N) etc.
            base_type = ftype_raw.split("(")[0].strip()
            drizzle_type = type_map.get(base_type, "text")
            imports.add(drizzle_type)

            col = f"  {fname}: {drizzle_type}(\"{fname}\")"
            if is_pk:
                col += ".primaryKey()"
            if not nullable and not is_pk:
                col += ".notNull()"
            if ftype_raw == "timestamp" and fname in ("created_at", "createdAt"):
                col += ".defaultNow()"
            field_lines.append(col + ",")

        # Ensure standard fields exist
        field_names = {f.get("name", "") for f in fields}
        if "created_at" not in field_names and "createdAt" not in field_names:
            imports.add("timestamp")
            field_lines.append('  createdAt: timestamp("created_at").defaultNow(),')
        if "updated_at" not in field_names and "updatedAt" not in field_names:
            imports.add("timestamp")
            field_lines.append('  updatedAt: timestamp("updated_at").defaultNow(),')

        var_name = table_name[0].lower() + table_name[1:] if table_name else "unknown"
        block = f'export const {var_name} = pgTable("{snake_name}", {{\n'
        block += "\n".join(field_lines)
        block += "\n});\n"
        table_code_blocks.append(block)

    # Build the full schema file
    import_list = sorted(imports)
    schema_content = f'import {{ {", ".join(import_list)} }} from "drizzle-orm/pg-core";\n\n'
    schema_content += "\n".join(table_code_blocks)

    schema_path.write_text(schema_content)
    logger.info(f"[schema] Generated src/db/schema.ts with {len(data_models)} models from plan")

    # Also generate src/db/index.ts if missing
    index_path = Path(output_dir) / "src" / "db" / "index.ts"
    if not index_path.exists():
        index_content = '''import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";
import * as schema from "./schema";

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

export const db = drizzle(pool, { schema });
'''
        index_path.write_text(index_content)


async def _persist_version(
    project_id: uuid.UUID,
    commit_hash: str,
    message: str,
) -> None:
    """Persist a version record in a new DB session."""
    from database import async_session
    async with async_session() as sess:
        version = Version(
            project_id=project_id,
            commit_hash=commit_hash,
            message=message,
        )
        sess.add(version)
        await sess.commit()
