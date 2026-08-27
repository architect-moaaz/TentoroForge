"""Single entry point for the generation pipeline.

Phase 1e (wrapper edition) — this is the ONE ENTRY POINT the plan doc
promised. It replaces the split between ``_run_relay_pipeline`` and
``_run_figma_relay_pipeline`` in :mod:`routers.generate` as the
caller's contract. Callers construct a :class:`PlanSource` and pass it
to :func:`run_pipeline`; this function dispatches on ``source.kind`` and
forwards to the correct legacy implementation.

**Scope of this file** (Phase 1e wrapper):

- ✅ ONE entry point (`run_pipeline`).
- ✅ Callers no longer pick between two functions.
- ✅ The ``PlanSource`` model is real and used in the codebase.
- ✅ Legacy pipelines become internal implementation detail; new code
  and future consumers only see ``run_pipeline``.

**Deferred to Phase 1e.2** (a follow-up dedicated to code motion):

- The legacy functions ``_run_relay_pipeline`` / ``_run_figma_relay_pipeline``
  in ``routers.generate`` stay in place and get invoked by this
  wrapper. Deleting them requires lifting the ~1400 lines of frontend
  authoring into :mod:`services.pipeline.phase_frontend` (contracts
  already locked in Phase 1d) plus lifting the ~530-line figma
  pre-phase block into :mod:`services.pipeline.phase_figma_pre`.
  That's a ~2000-line atomic edit best done in a dedicated session
  with fixture snapshots in hand.

**Zero behaviour change from this wrapper:** it forwards every arg to
the exact same legacy function that used to be called directly. The
call graph gains one hop through this dispatcher; nothing else changes.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from services.pipeline.source import PlanSource


async def run_pipeline(
    *,
    output_dir: str,
    plan: dict,
    description: str,
    source: PlanSource,
    project_id: Any = None,
    domain_context: Optional[dict] = None,
    # These extras are accepted so `orchestrate_generation` can forward
    # its full kwargs bundle without the caller having to strip anything:
    figma_context: Optional[dict] = None,     # Absorbed; source.figma_context wins.
    figma_url: Optional[str] = None,          # Absorbed for back-compat; source.figma_url wins.
    figma_token: Optional[str] = None,        # Absorbed for back-compat; source.figma_token wins.
    **_ignored_extras: Any,
) -> AsyncIterator[dict]:
    """Dispatch the generation pipeline based on ``source.kind``.

    Preferred call shape — the only public entry point:

        async for evt in run_pipeline(
            output_dir=out,
            plan=plan,
            description=description,
            source=PlanSource.text(),
            project_id=project.id,
            domain_context=discovery_dossier,
        ):
            ...

    Or for Figma:

        async for evt in run_pipeline(
            output_dir=out,
            plan=plan,
            description=description,
            source=PlanSource.figma(url=url, token=token),
            project_id=project.id,
            domain_context=discovery_dossier,
        ):
            ...
    """
    # Lazy import — the legacy functions live in routers.generate and
    # importing that module at the top pulls in the FastAPI router
    # plus its full dependency graph. Defer to call time so this module
    # stays cheap to import (matters for the test suite).
    from routers.generate import _run_relay_pipeline, _run_figma_relay_pipeline

    if source.is_text:
        async for evt in _run_relay_pipeline(
            output_dir=output_dir,
            plan=plan,
            description=description,
            figma_context=source.figma_context,  # None for text sources.
            project_id=project_id,
            domain_context=domain_context,
        ):
            yield evt
        return

    # Figma path — source.figma_url is guaranteed non-empty by
    # PlanSource.__post_init__. If a legacy caller still passes
    # figma_url/figma_token as loose kwargs (from before this
    # wrapper existed), the source's own fields win.
    async for evt in _run_figma_relay_pipeline(
        output_dir=output_dir,
        plan=plan,
        description=description,
        figma_url=source.figma_url,
        figma_token=source.figma_token,
        project_id=project_id,
        domain_context=domain_context,
    ):
        yield evt
