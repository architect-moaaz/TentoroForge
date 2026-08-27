"""Narrator-mode agent adapters — Migration Step 1.

Bridges the existing agent functions (`agents/discovery.py`,
`agents/planner.py`, `agents/code_generator.py`) to the narrator
artifact shapes (`services/narrator_artifacts.py`).

The agents themselves are heavy — they yield streaming `Message`
objects, use `claude_agent_sdk.query`, and are wired into the SSE
pipeline. This module provides two things:

  1. **Pure normalization helpers** — take an already-produced
     artifact (a plan dict, an accumulated text stream, a file
     listing) and return the corresponding narrator artifact. These
     are the tested surface.

  2. **Optional live orchestrators** — thin functions that call the
     real agent, accumulate the stream, and hand off to the pure
     helper. These land at wire-in time (Step 3+) and are
     intentionally lazy imports so tests don't drag the SDK.

Callers (Migration Step 3, the new POST /chat/message handler)
compose a full SmithSession seam by wrapping these.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os as _os
import re
from pathlib import Path
from typing import Any, Iterable

from services.narrator_artifacts import (
    DiscoveryArtifact,
    GeneratorArtifact,
    NarratorArtifactError,
    PlannerArtifact,
)


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Planner
# --------------------------------------------------------------------------- #

def plan_dict_to_artifact(plan: dict[str, Any]) -> PlannerArtifact:
    """Normalize the plan dict `run_planner_oneshot` returns into a
    PlannerArtifact.

    The planner emits `models` (entities), `workflows`, and `pages`.
    Field names differ from the artifact shape, so we rename +
    fill in derived fields (schema_path from route)."""
    if not isinstance(plan, dict):
        raise NarratorArtifactError("plan must be an object")

    entities = []
    for m in plan.get("models") or []:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        fields = m.get("fields") or []
        key_fields = [
            str(f.get("name")) for f in fields
            if isinstance(f, dict) and f.get("name")
        ][:8]
        entities.append({
            "name": str(m["name"]),
            "table": str(m.get("table") or _default_table_for(m["name"])),
            "purpose": str(m.get("purpose") or m.get("description") or ""),
            "key_fields": key_fields,
            "why_shaped_this_way": str(m.get("why") or ""),
        })

    workflows = []
    for w in plan.get("workflows") or []:
        if not isinstance(w, dict) or not w.get("name"):
            continue
        workflows.append({
            "name": str(w["name"]),
            "purpose": str(w.get("purpose") or w.get("description") or ""),
            "trigger": _extract_trigger(w.get("trigger")),
            "why": str(w.get("why") or ""),
        })

    pages = []
    for p in plan.get("pages") or []:
        if not isinstance(p, dict) or not p.get("route"):
            continue
        route = str(p["route"])
        pages.append({
            "route": route,
            "schema_path": str(p.get("schema_path") or _schema_path_for(route)),
            "role": str(p.get("role") or p.get("type") or ""),
        })

    return PlannerArtifact.from_dict({
        "entities": entities, "workflows": workflows, "pages": pages,
    })


def _merge_revised_plan(*, prior: dict, revised: dict) -> dict:
    """Merge a critic-revised plan back onto its prior version.

    Truth: the LLM sometimes emits a partial revision after a critic
    turn — only the touched sections. We must not lose ``data_models``,
    ``access_control``, ``description``, ``module_name`` etc. just
    because the actor decided to focus its response on workflows.

    Strategy: for every top-level key, prefer the revised value ONLY
    when it's non-empty; otherwise fall back to the prior value. This
    lets genuine revisions land (a smaller list, an edited entry) but
    guarantees no accidental blanking. Nested dicts and lists are
    treated atomically — we don't merge inside a workflow definition,
    because the actor authored it whole."""
    if not isinstance(revised, dict):
        return prior
    if not isinstance(prior, dict):
        return revised
    out: dict = dict(prior)
    for k, v in revised.items():
        if v is None:
            continue
        if isinstance(v, (list, dict, str)) and not v:
            # Empty list / dict / string in revision = drop, keep prior
            continue
        out[k] = v
    return out


def _extract_trigger(t: Any) -> str:
    """Normalize a workflow ``trigger`` field to a string.

    The planner emits inconsistently — sometimes ``"form_submit"`` (str),
    sometimes ``{"type": "form_submit"}`` (dict), sometimes missing.
    The narrator artifact only needs the type string; be liberal on
    input, strict on output."""
    if isinstance(t, str):
        return t
    if isinstance(t, dict):
        return str(t.get("type") or "")
    return ""


def _default_table_for(entity_name: str) -> str:
    """Best-effort table name when the plan didn't specify one.

    Planners today usually emit `table` explicitly; this is only a
    fallback so the adapter doesn't crash on old plans."""
    s = str(entity_name or "").strip()
    if not s:
        return ""
    # Naive plural; the real system has services.entity_names for
    # this. Adapter doesn't import it to keep the dep graph clean.
    return (s[0].lower() + s[1:]) + "s"


def _schema_path_for(route: str) -> str:
    """Derive src/schemas/… from a route.

    /candidates → src/schemas/candidates/index.json
    /candidates/new → src/schemas/candidates/new.json
    /drives/[id]/edit → src/schemas/drives/[id]/edit.json
    """
    r = (route or "").strip().lstrip("/")
    if not r:
        return ""
    if "/" not in r:
        return f"src/schemas/{r}/index.json"
    return f"src/schemas/{r}.json"


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #

# The discovery agent emits ```discovery-brief\n{JSON}\n``` at the
# end of its stream. We accept a couple of language variants so a
# minor prompt drift doesn't break the adapter.
_DISCOVERY_BRIEF_RE = re.compile(
    r"```(?:discovery-brief|discovery_brief|dossier)\s*\n(.*?)\n```",
    re.DOTALL,
)


def discovery_stream_to_artifact(accumulated_text: str) -> DiscoveryArtifact:
    """Parse the accumulated stream text from `run_discovery` and
    normalize the discovery-brief block into a DiscoveryArtifact.

    Callers (the live orchestrator) are responsible for collecting
    every chunk from the AsyncIterator into `accumulated_text`;
    this function is pure."""
    if not isinstance(accumulated_text, str) or not accumulated_text.strip():
        raise NarratorArtifactError("empty discovery stream")

    m = _DISCOVERY_BRIEF_RE.search(accumulated_text)
    if not m:
        raise NarratorArtifactError(
            "no ```discovery-brief``` block in stream — the agent did "
            "not complete its dossier"
        )
    try:
        payload = json.loads(m.group(1))
    except (ValueError, TypeError) as exc:
        raise NarratorArtifactError(
            f"discovery-brief block is not valid JSON: {exc}"
        ) from exc
    return DiscoveryArtifact.from_dict(payload)


# --------------------------------------------------------------------------- #
# Generator
# --------------------------------------------------------------------------- #

_GENERATOR_SKIP_DIRS = frozenset({
    ".git", "node_modules", ".next", ".turbo", ".venv", "__pycache__",
})


def generator_files_to_artifact(
    *, output_dir: str,
    warnings: Iterable[str] | None = None,
    notes: Iterable[str] | None = None,
) -> GeneratorArtifact:
    """Snapshot the generated file tree into a GeneratorArtifact.

    Enumerates every file under `output_dir` that's not in a
    junk directory (`_GENERATOR_SKIP_DIRS`). Warnings and notes are
    passed through — production callers accumulate them from
    post_generate_fixes log capture."""
    root = Path(output_dir)
    files: list[str] = []
    if root.is_dir():
        for p in _walk_files(root):
            files.append(str(p.relative_to(root)))
    return GeneratorArtifact.from_dict({
        "generated_files": sorted(files),
        "warnings": list(warnings or []),
        "notes": list(notes or []),
    })


def _walk_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # Skip anything whose relative path traverses a junk dir.
        rel_parts = path.relative_to(root).parts
        if any(seg in _GENERATOR_SKIP_DIRS for seg in rel_parts):
            continue
        yield path


# --------------------------------------------------------------------------- #
# Live orchestrators — Migration Step 1 Option A
#
# These wrap the actual running agents so Smith can call them as his
# own moves. Each orchestrator does the plumbing between an
# artifact-shaped seam signature (what SmithSession expects) and the
# real agent's async / streaming API.
#
# Kept in this module (not smith_architect_wire) because they're
# reusable outside the bootstrap chat-handler wiring — anything that
# wants a normalized artifact from a real agent call comes through
# these three functions.
# --------------------------------------------------------------------------- #

async def orchestrate_discovery(
    *,
    output_dir: str,
    user_message: str,
    org_context: str | None = None,
    conversation_history: list | None = None,
) -> DiscoveryArtifact:
    """Run domain discovery once and normalize the dossier into a
    DiscoveryArtifact for Smith to narrate.

    Uses ``agents.domain_agent.run_domain_discovery`` — a single-shot
    LLM call that returns a full dossier immediately (not the multi-turn
    Q&A discovery from ``agents.discovery``, which would sit waiting
    for the user's reply on a first turn).

    The full raw dossier is attached as ``artifact._raw_dossier`` so
    callers (``run_bootstrap_stage``, ``record_discovery``, SSE
    emitters) can access fields the DiscoveryArtifact shape doesn't
    preserve (personas, designPatterns, visualLanguage, colorAnchors,
    complianceNotes, formPatterns, entitySuggestions.likelyFields).
    """
    from agents.domain_agent import run_domain_discovery

    dossier = await run_domain_discovery(
        user_message, plan=None, enable_web_search=True,
    )
    artifact = _domain_dossier_to_artifact(dossier)
    # Preserve the full raw dossier on the artifact for downstream
    # consumers that want fields the DiscoveryArtifact doesn't carry.
    try:
        setattr(artifact, "_raw_dossier", dict(dossier))
    except Exception:  # noqa: BLE001
        pass
    return artifact


def _domain_dossier_to_artifact(dossier: dict) -> DiscoveryArtifact:
    """Translate a domain_agent DiscoveryOutput dict → DiscoveryArtifact.

    Field mapping:
      domain              → domain_name
      entitySuggestions[] → proposed_entities[] (name + why from likelyFields)
      uncertainAreas[]    → open_questions[]
      designPatterns[]    → distinctive_shape (joined pattern names)
      confidence          → confidence
      actors, verbs       → left empty (domain dossier doesn't carry these;
                            the multi-turn run_discovery does, but that
                            can't run on a first turn without a user reply).
    """
    if not isinstance(dossier, dict):
        raise NarratorArtifactError("domain dossier must be a dict")

    domain_name = str(dossier.get("domain") or "").strip()
    if not domain_name:
        raise NarratorArtifactError(
            "domain_agent returned no `domain` — cannot narrate a nameless app"
        )

    entities_raw = dossier.get("entitySuggestions") or []
    proposed_entities = []
    for e in entities_raw:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        likely = e.get("likelyFields") or []
        why = (
            f"key fields: {', '.join(str(f) for f in likely[:4])}"
            if likely else "identified in domain research"
        )
        proposed_entities.append({"name": str(e["name"]), "why": why})

    open_questions = [
        str(q) for q in (dossier.get("uncertainAreas") or []) if q
    ]

    distinctive_bits: list[str] = []
    for p in (dossier.get("designPatterns") or []):
        if isinstance(p, dict) and p.get("name"):
            distinctive_bits.append(str(p["name"]))
    distinctive_shape = ", ".join(distinctive_bits[:4])

    try:
        conf = float(dossier.get("confidence", 0.7))
    except (TypeError, ValueError):
        conf = 0.7

    return DiscoveryArtifact.from_dict({
        "domain_name": domain_name,
        "actors": [],
        "verbs": [],
        "distinctive_shape": distinctive_shape,
        "proposed_entities": proposed_entities,
        "open_questions": open_questions,
        "confidence": conf,
    })


async def orchestrate_planner(
    *,
    description: str,
    domain_context: dict | None = None,
    prior_plan: dict | None = None,
    # 900s (15 min) — streaming a 32K-token plan is sequential; a rich
    # ATS plan can take 5-8 min to fully emit. Matches
    # run_planner_oneshot's default so both paths align.
    timeout_seconds: float = 900.0,
    emit_fn: Any = None,
    output_dir: str | None = None,
    structured_brief: Any = None,
) -> PlannerArtifact:
    """Actor-Critic planner: draft → critique → revise (up to 3 turns).

    Turn 0 runs ``run_planner_oneshot`` normally. Turns 1-3 run the
    critic loop from ``agents.plan_critic.critique_plan`` — approve
    returns the plan, revise feeds the critic's gaps back into a
    fresh planner call via ``build_actor_retry_prompt``, reject or
    cap ships the best-so-far (fewest blockers, tiebreak fewest
    important).

    Off by default. Set ``FORGE_SMITH_PLANNER_CRITIC=1`` to opt in.
    Kept off because the extra turns add latency without a matching
    quality win in the current planner.

    ``emit_fn(stage, payload)`` — optional callback to surface critic
    progress as SSE events. Silent when omitted."""
    from agents.planner import run_planner_oneshot
    from services.plan_wire_pipeline import (
        apply_narrative_expansion, apply_plan_wires,
    )

    def _emit(stage: str, text: str, data: dict | None = None) -> None:
        if emit_fn is None:
            return
        try:
            emit_fn(stage, {"text": text, **(data or {})})
        except Exception:  # noqa: BLE001 — caller's emitter, never break planning
            logger.exception("orchestrate_planner: emit(%s) failed", stage)

    # Narrative expansion — pre-planner LLM turn that enriches the
    # sparse user prompt into a rich domain doc. Env-gated
    # ``FORGE_NARRATIVE_EXPANSION``; falls through unchanged when off
    # or when the expansion call fails. Persisted to
    # ``<output_dir>/contracts/domain-narrative.md``. ``emit_fn`` is
    # threaded through so the ~30-90s call surfaces typewriter progress
    # SSE events (see services/streaming_llm.py).
    description = await apply_narrative_expansion(
        description, structured_brief=structured_brief, output_dir=output_dir,
        emit_fn=emit_fn,
    )

    # ── Decomposition branch (Task 3): for large/complex prompts route
    # through the two-stage skeleton→parallel-units adapter instead of
    # one giant streaming call. Skeleton is ~5K output tokens (~1 min);
    # per-page authoring runs concurrently (bounded semaphore) so a
    # 20-page ATS finishes in ~1 more min instead of ~10. The assembled
    # dict is shape-identical to a one-shot plan, so downstream wire
    # passes + emitters consume it unchanged. On ANY failure at ANY
    # stage, fall through to the one-shot path.
    plan_dict: dict | None = None
    try:
        from services.app_decomposition import should_decompose
        _decompose = bool(should_decompose(description))
        # SPEED (Task 3): honour the profile's decomposition flag. Fast sets it
        # False → the quick one-shot planner (with revise skipped) instead of the
        # slow per-unit authoring path that made a simple app crawl.
        if _decompose and output_dir:
            try:
                from services.generation_profile import load_profile
                _pf_dec = load_profile(output_dir)
                if _pf_dec is not None and not _pf_dec.decomposition:
                    _decompose = False
                    logger.info("orchestrate_planner: profile=%s → one-shot (no decompose)", _pf_dec.id)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        logger.exception(
            "orchestrate_planner: should_decompose crashed; using one-shot"
        )
        _decompose = False

    if _decompose and output_dir is not None:
        _emit("planner_decompose_start",
              "Large app — decomposing plan into parallel per-page authoring")
        try:
            from agents.app_map_agent import run_app_map_planner
            from services.per_unit_authoring import author_all_units_async
            # run_app_map_planner is SYNC and calls asyncio.run() internally on
            # its LLM coroutine, which explodes when invoked from an already-
            # running event loop (which we ARE — orchestrate_planner is async).
            # asyncio.to_thread runs the sync function in a fresh worker thread
            # with no active loop, so its internal asyncio.run() works. This
            # sidesteps the nested-event-loop bug without changing the sync
            # function's signature (the classic produce_plan path stays
            # byte-unchanged).
            skeleton = await asyncio.to_thread(
                run_app_map_planner, description, domain_context,
            )
            plan_dict = await author_all_units_async(
                skeleton, output_dir, emit_fn=emit_fn,
            )
            _emit(
                "planner_decompose_complete",
                f"Decomposition complete — {len(plan_dict.get('pages') or [])} page(s) authored",
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "orchestrate_planner: decomposition failed; falling back to one-shot"
            )
            _emit(
                "planner_decompose_error",
                "Decomposition failed — falling back to one-shot planner",
            )
            plan_dict = None  # trigger the one-shot path below

    # ── Turn 0: initial plan (one-shot path — used when decomposition
    # declined, was not eligible, or failed). ────────────────────────
    if plan_dict is None:
        # SPEED (Task 3): the smith-arch planner was profile-BLIND — it never
        # read the user's Fast/Complete choice, so a "fast" build ran the full
        # planner INCLUDING the completeness-revise (a second full ~24K-token
        # plan re-stream, +4-8 min). Read the persisted profile and, for Fast,
        # skip that revise. Complete keeps it. (produce_plan was fixed last round
        # but this smith-arch path — the one actually used now — was not.)
        _allow_revise = True
        if output_dir:
            try:
                from services.generation_profile import load_profile
                _pf = load_profile(output_dir)
                if _pf is not None:
                    _allow_revise = bool(_pf.planner_revise)
            except Exception:  # noqa: BLE001 — never block planning on this
                pass
        plan_dict = await run_planner_oneshot(
            description,
            domain_context=domain_context,
            timeout_seconds=timeout_seconds,
            prior_plan=prior_plan,
            emit_fn=emit_fn,
            allow_revise=_allow_revise,
        )
    plan_dict = apply_plan_wires(plan_dict)

    def _pack(pd: dict) -> PlannerArtifact:
        """Build PlannerArtifact + attach raw plan dict so downstream
        consumers (SSE plan_ready, PlanCard) get workflow steps,
        entity fields, page metadata — not just the narrator's minimal
        summary shape."""
        art = plan_dict_to_artifact(pd)
        try:
            setattr(art, "_raw_plan", pd)
        except Exception:  # noqa: BLE001
            pass
        return art

    critic_on = _os.environ.get("FORGE_SMITH_PLANNER_CRITIC", "0").strip() == "1"
    if not critic_on:
        return _pack(plan_dict)

    # ── Turns 1-3: Actor-Critic loop ─────────────────────────────────
    try:
        from agents.plan_critic import critique_plan
        from services.plan_critic_prompt import build_actor_retry_prompt
        from services.plan_validator import validate_plan
    except Exception:  # noqa: BLE001 — critic stack unavailable; ship the draft
        logger.exception(
            "orchestrate_planner: critic imports failed; shipping first-draft plan"
        )
        return _pack(plan_dict)

    _emit("critic_start", "Reviewing plan quality with the critic")
    history: list[dict] = []
    prior_gaps: list[dict] = []
    current_plan = plan_dict

    for turn in range(1, 4):
        _emit(
            "critic_turn_start",
            f"Critic turn {turn} — reviewing plan",
            {"turn": turn},
        )
        try:
            det_violations = validate_plan(current_plan)
        except Exception:  # noqa: BLE001
            det_violations = []
        try:
            critique = await critique_plan(
                plan=current_plan,
                user_brief=description,
                deterministic_violations=det_violations,
                prior_critic_gaps=prior_gaps,
            )
        except Exception:  # noqa: BLE001 — critic is defensive but belt-and-suspenders
            logger.exception(
                "orchestrate_planner: critique_plan crashed on turn %d", turn
            )
            _emit(
                "critic_retry_error",
                f"Critic crashed on turn {turn} — shipping best plan so far",
                {"turn": turn},
            )
            break

        gaps = critique.get("gaps") or []
        n_blockers = sum(1 for g in gaps if g.get("severity") == "blocker")
        n_important = sum(1 for g in gaps if g.get("severity") == "important")
        verdict = critique.get("verdict") or "approve"
        domain = str(critique.get("inferred_domain") or "")[:60]
        logger.info(
            "[smith-planner-critic] turn %d verdict=%s blockers=%d important=%d domain=%s",
            turn, verdict, n_blockers, n_important, domain,
        )
        _emit(
            "critic_verdict",
            (
                f"Turn {turn} ({domain}): {verdict} — "
                f"{n_blockers} blocker(s), {n_important} important"
            ),
            {
                "turn": turn, "verdict": verdict,
                "blockers": n_blockers, "important": n_important,
                "domain": domain,
            },
        )
        history.append({
            "plan": current_plan, "verdict": verdict, "gaps": gaps,
            "n_blockers": n_blockers, "n_important": n_important,
        })

        if verdict == "reject":
            _emit(
                "critic_rejected",
                f"Critic rejected the plan on turn {turn}",
                {"turn": turn},
            )
            break

        if verdict == "approve":
            _emit(
                "critic_approved",
                f"Plan approved on turn {turn}",
                {"turn": turn},
            )
            return _pack(current_plan)

        # revise → invoke actor with the corrective prompt
        if turn == 3:
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
        try:
            retry_prompt = build_actor_retry_prompt(
                original_brief=description,
                prior_plan=current_plan,
                critic_gaps=gaps,
            )
            revised = await run_planner_oneshot(
                retry_prompt,
                domain_context=domain_context,
                timeout_seconds=timeout_seconds,
            )
            revised = apply_plan_wires(revised)
            # LLM over-revises — even with a "preserve the rest" instruction
            # it sometimes drops whole sections (data_models, access_control,
            # description). Merge revised onto prior so we never lose ground.
            current_plan = _merge_revised_plan(prior=current_plan, revised=revised)
            prior_gaps = gaps
        except Exception:  # noqa: BLE001 — actor crashed; ship best-so-far
            logger.exception(
                "orchestrate_planner: actor retry crashed on turn %d", turn
            )
            _emit(
                "critic_retry_error",
                "Revision crashed — shipping best plan so far",
                {"turn": turn},
            )
            break

    # Ship best-so-far when we broke out without an approve.
    if history:
        best = min(
            history, key=lambda h: (h["n_blockers"], h["n_important"]),
        )
        return _pack(best["plan"])
    return _pack(current_plan)


def orchestrate_generator_snapshot(
    *,
    output_dir: str,
    warnings: Iterable[str] | None = None,
    notes: Iterable[str] | None = None,
) -> GeneratorArtifact:
    """Snapshot the generated file tree into an artifact.

    Post-hoc read — used AFTER ``orchestrate_generation`` completes to
    capture the final file set for the change log. The live orchestration
    happens in :func:`orchestrate_generation` below."""
    return generator_files_to_artifact(
        output_dir=output_dir,
        warnings=warnings,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Live generator invocation — Smith calls the pipeline as HIS tool.
#
# Prior to this, ``_run_relay_pipeline`` in ``routers/generate.py`` ran
# autonomously — the HTTP endpoint kicked it off directly. That's the
# "pipeline runs itself" shape. This adapter turns it into a tool Smith
# owns: he opens with architect-voice prose, forwards every SSE event
# from the underlying pipeline, and closes with architect-voice prose
# reflecting what actually landed.
#
# The pipeline function is INJECTED (``pipeline_fn`` kwarg) — this
# module never imports ``routers/generate.py`` at import time so the
# dependency graph stays clean and tests exercise the orchestrator
# without dragging the whole HTTP stack.
# --------------------------------------------------------------------------- #

async def orchestrate_generation(
    *,
    pipeline_fn,
    output_dir: str,
    project_id,
    plan: dict,
    description: str,
    figma_context: dict | None = None,
    domain_context: dict | None = None,
    user_ask: str = "",
    **pipeline_kwargs,
):
    """Async generator: Smith invokes the build pipeline as his tool.

    Yields event dicts in the same shape ``_run_relay_pipeline`` yields,
    bracketed by two ``smith_narration`` events:

      * OPEN: architect-voice ``generation_handoff`` prose before the
        first pipeline event.
      * CLOSE: architect-voice ``generation_complete`` prose after the
        last pipeline event, informed by the actual file tree.

    On pipeline exception, yields the CLOSE narration explaining what
    went wrong, then re-raises. Never swallows the pipeline error."""
    from services.smith_narrator import narrate

    # OPEN — Smith opens the build. Matches pipeline event shape:
    # {"event": "...", "data": json_string} — anything else crashes
    # sse_starlette when the response tries ServerSentEvent(**dict).
    yield {
        "event": "smith_narration",
        "data": json.dumps({
            "stage": "generation_handoff",
            "prose": narrate(
                stage="generation_handoff",
                fallback=(
                    "Kicking off the build. I'll narrate as pages, "
                    "workflows, and schemas materialize."
                ),
                user_ask=user_ask,
            ),
        }),
    }

    # Forward every non-None kwarg to the pipeline. figma_context is
    # only appropriate for _run_relay_pipeline; the figma pipeline
    # takes figma_url/figma_token in **pipeline_kwargs instead.
    call_kwargs = {
        "output_dir": output_dir,
        "plan": plan,
        "description": description,
        "project_id": project_id,
        "domain_context": domain_context,
    }
    if figma_context is not None:
        call_kwargs["figma_context"] = figma_context
    call_kwargs.update(pipeline_kwargs)

    error: Exception | None = None
    try:
        async for evt in pipeline_fn(**call_kwargs):
            yield evt
    except Exception as exc:  # noqa: BLE001
        error = exc
        # Fall through so we still emit the CLOSE narration below,
        # then re-raise after.

    # CLOSE — Smith reports what actually happened, using the file
    # tree as ground truth (not the pipeline's self-report).
    snapshot = generator_files_to_artifact(output_dir=output_dir)
    close_fallback = (
        f"Build failed: {type(error).__name__}: {error}"
        if error is not None
        else snapshot.narrator_summary()
    )
    yield {
        "event": "smith_narration",
        "data": json.dumps({
            "stage": "generation_complete",
            "prose": narrate(
                stage="generation_complete",
                artifact=snapshot,
                fallback=close_fallback,
                user_ask=user_ask,
            ),
            "files_count": len(snapshot.generated_files),
            "error": None if error is None else f"{type(error).__name__}: {error}",
        }),
    }

    if error is not None:
        raise error
