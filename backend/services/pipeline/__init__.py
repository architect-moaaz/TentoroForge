"""Generation pipeline: one spine, per-phase extract, source-conditional.

See docs/superpowers/plans/2026-08-12-pipeline-cleanup.md for the plan.

The pipeline collapses today's `_run_relay_pipeline` (text) and
`_run_figma_relay_pipeline` (Figma) into a single orchestrator that reads
a :class:`PlanSource` to decide which per-phase variants to invoke.

Public surface (used by :mod:`routers.generate`):

- :class:`PlanSource` — declares whether the plan came from text or Figma
  and carries the Figma-only inputs.
- :func:`run_pipeline` — the single spine, replaces the two functions.
- :mod:`phases` — one function per pipeline phase (extracted from the
  originals so the spine is a straight sequence of calls).
"""
from services.pipeline.source import PlanSource  # noqa: F401
from services.pipeline.spine import run_pipeline  # noqa: F401
