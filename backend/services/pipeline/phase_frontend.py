"""Frontend authoring — Phase 4/5 of the generation pipeline.

Phase 1d of the pipeline cleanup. These functions are the biggest single
chunks in the legacy pipelines (~590 + ~270 lines respectively). Rather
than lift them byte-for-byte here (creating 800+ lines of duplicated
code in the tree until Phase 1e wires them in and deletes the originals),
this module locks the **contract** — signatures + closure-var thread
list + line-range map — and defers the actual code motion to Phase 1e
where the new spine gets written in one atomic swap.

Why extract-in-place doesn't fit Phase 1d:
- Text frontend is ~590 lines with three branches (SCHEMA / IR / LLM),
  five post-gates (PAGE, CROSS-REF, UX TOLL, WORKFLOW, executability),
  and mutates ``registry`` + ``plan``.
- Figma frontend is ~270 lines but sits AFTER a ~530-line pre-block
  (deterministic mapper + schema refiner + MCP + binding pass — see
  :mod:`services.pipeline.phase_figma_pre`) and calls the same
  ``run_schema_frontend_pipeline`` with a ``skip_routes`` filter.
- Neither has runtime tests. A missed closure var = silent breakage in
  the critical path.
- Phase 1e writes the new spine anyway; doing the code motion as ONE
  atomic edit there (out of ``generate.py``, into ``phase_frontend``,
  wired into ``run_pipeline``, delete originals) is safer than
  duplicating 800 lines here for Phase 1e to later reconcile.

The extracts land in Phase 1e using the contracts declared here.
"""
from __future__ import annotations

from typing import AsyncIterator, Optional

from services.pipeline.state import PipelineState


# =============================================================================
# Text frontend — Phase 4-5 authoring for text-driven generations
# =============================================================================


async def phase_frontend_text(
    state: PipelineState,
    plan: dict,
    *,
    registry: dict,          # mutated in place (auth_routes, pages sections)
    domain_ctx: Optional[dict] = None,
    project_short_id: str,   # Path(output_dir).name — passed in for readability
    project_id=None,         # for auth-page emit + workflow scaffolds
    chat_flavor_module=None, # services.chat_flavor — passed in to avoid re-import
) -> AsyncIterator[dict]:
    """Text pipeline Phase 4-5 — frontend authoring + post-frontend gates.

    **Lift source:** ``routers.generate._run_relay_pipeline`` lines 2463-3055.

    **Three internal branches (mutually exclusive, decided by env/plan flags):**

    1. **SCHEMA branch** (default) — deterministic-first page emission via
       ``run_schema_frontend_pipeline``, with:
       - ``nav_flow_from_plan`` + ``shell_layout_agent`` preludes
       - ``stage_plan`` preview emission
       - auth-route filtering + ``emit_auth_page_schemas`` for login/signup

    2. **IR branch** (behind ``services.ir_pipeline.IR_FRONTEND_ENABLED``)
       — ``run_ir_frontend_pipeline``.

    3. **LLM branch** (default when neither of the above matches) —
       legacy component_agent + page_completeness via ``run_figma_ui_agent``.
       Slowest path, still supported for regression comparison.

    **Post-frontend gates (all run after the branch dispatch):**

    - **PAGE GATE** (2867-2883): assert every plan.pages has a schema file;
      backstop-fill missing via ``fill_missing_pages``.
    - **CROSS-REFERENCE GATE** (2901-2912): pages that navigate to non-existent
      routes get patched.
    - **UX TOLL GATE** (2914-2927): drops LLM-hallucinated components not in
      the library allowlist.
    - **WORKFLOW SCAFFOLDS** (2929-2964): fallback `generate_workflow_definitions`
      for plans with workflows the deterministic emitter didn't cover.
    - **WORKFLOW GATE** (2986-3055): validity + executability + graph gate;
      LLM-repairs unresolvable steps.

    **Closure vars threaded in (all currently locals of _run_relay_pipeline):**

    - ``registry`` — dict, mutated to add pages/routes sections. Callers pass
      the shared spine dict; this function mutates in place.
    - ``project_short_id`` — Path(output_dir).name; used as
      ``ProgressTracker`` identifier + shell layout context.
    - ``project_id`` — Optional[UUID]; forwarded to workflow scaffolds +
      auth page emit.
    - ``chat_flavor`` — module handle for narrator lines (`chat_flavor.start`
      / `chat_flavor.done` / `chat_flavor.ready`). Passed as
      ``chat_flavor_module`` for testability.
    - ``domain_ctx`` — the discovery dossier; forwarded to page-schema /
      component / IR / LLM agents.
    - ``state.stream_phase(...)`` — every agent invocation goes through here.
    - ``state.progress`` — for phase_start ping at each sub-stage.
    - ``state.drain_progress()`` — to emit buffered progress events.

    **Emits:** SSE events (status, log, message, resource, page_schema,
    workflow_scaffold, cta_report, coverage_verdict, pd_report).

    **Returns:** None (generator). Mutates ``registry`` and (sometimes) ``plan``.
    """
    raise NotImplementedError(
        "phase_frontend_text: contract locked in Phase 1d; body lifts from "
        "routers.generate lines 2463-3055 during Phase 1e when the new "
        "spine is written."
    )
    # Placate the type checker — this line is unreachable.
    yield {}


# =============================================================================
# Figma frontend — Phase 4-5 authoring for Figma-driven generations
# =============================================================================


async def phase_frontend_figma(
    state: PipelineState,
    plan: dict,
    *,
    registry: dict,
    domain_ctx: Optional[dict] = None,
    project_short_id: str,
    project_id=None,
    deterministic_pages: set[str],   # populated by phase_figma_deterministic_map
    chat_flavor_module=None,
) -> AsyncIterator[dict]:
    """Figma pipeline Phase 4-5 — frontend authoring.

    **Lift source:** ``routers.generate._run_figma_relay_pipeline`` lines 4650-4918.

    **Runs AFTER** :mod:`services.pipeline.phase_figma_pre` has already
    emitted deterministic page schemas from the Figma mapper. This phase
    fills any gaps with the SCHEMA or LLM branch.

    **Two internal branches:**

    1. **SCHEMA branch** (default) — ``run_schema_frontend_pipeline`` with
       ``skip_routes=deterministic_pages`` so the LLM doesn't overwrite
       pages the Figma mapper already emitted.

    2. **LLM branch** (fallback when SCHEMA branch declines) —
       ``run_figma_ui_agent`` monolithic call. Slowest; primarily for
       regression baselines.

    **INTENTIONALLY OMITS** the text-pipeline post-frontend gate cluster
    (PAGE, CROSS-REF, UX TOLL, WORKFLOW GATE, executability). Under
    "Behaviour preservation A-strict" (see plan doc §Q1) these gaps are
    preserved in Phase 1 and become follow-ups for later phases:
    - Phase 4 (renderer contract) may add nav-flow parity.
    - Phase 6 (authority collapse) is where dashboards / forms / shells
      get single-writer authority that makes the gates redundant.

    **Closure vars threaded in:**

    - Same set as :func:`phase_frontend_text`, plus:
    - ``deterministic_pages`` — set[str] of route paths the Figma mapper
      already covered; the SCHEMA branch skips those to prevent double-writes.

    **Returns:** None (generator). Mutates ``registry``.
    """
    raise NotImplementedError(
        "phase_frontend_figma: contract locked in Phase 1d; body lifts from "
        "routers.generate lines 4650-4918 during Phase 1e when the new "
        "spine is written."
    )
    yield {}
