"""Phase 7 — post-generate consolidation bookkeeping.

The suite in :mod:`services.post_generate_fixes` grew organically to ~50 guards.
Two things were missing:

1. A declared PHASE ORDER, so a reader can see what runs when without
   walking 1800 lines of try/except.
2. A GUARD-ONCE COUNTER, so a duplicate call to
   ``apply_post_generate_fixes`` for the same generation shows up in logs
   instead of silently double-running (which used to happen — the router
   called it from four different pipeline branches; see routers/generate.py
   for line 2637, 3075, 4536, 4705).

This module gives both. The phase enum is intentionally coarse (~8
groups) rather than one entry per guard: fine-grained per-guard
declaration would drift the moment a guard is added, whereas grouping is
stable and documents intent. Existing guards need NO changes to benefit
from the run counter — the counter is driven from the entry point in
``apply_post_generate_fixes``, not from each guard.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


class PostGenPhase(IntEnum):
    """Declared execution order of ``apply_post_generate_fixes``.

    Ordinal encodes precedence: SCHEMA_INTEGRITY must complete before any
    guard that reads a schema file, PAGE_COMPOSITION must complete before
    UI_POLISH asserts against composer output, etc. The linear code in
    ``apply_post_generate_fixes`` is the source of truth; this enum
    documents the intent so a reader can find the section quickly.
    """

    SCHEMA_INTEGRITY = 1
    """JSON repair, dedup, import reconciliation. Runs first — every
    later guard reads schema files."""

    WORKFLOW_INTEGRITY = 2
    """Workflow table wiring, mutation heal, list-entity coherence."""

    DB_INTEGRITY = 3
    """Drizzle column + FK type constraints (fatal if wrong — Postgres
    rejects the migration)."""

    FORM_AUTHORING = 4
    """Form scaffold, semantic field types, FK dropdown repair, enum
    selects, required markers."""

    PAGE_COMPOSITION = 5
    """Signature moves, illustrated empty states, dashboard / collection
    / record maquette composers (Phase 2 + 3 + 6 authority)."""

    ROUTE_RECONCILIATION = 6
    """Ensure create/edit routes, nav route reconcile, detail action
    wiring, table row nav, auth-gate."""

    UI_POLISH = 7
    """Surface border harmonize, surface wrap (assert-only under
    authority), chart data source, motion tokens, mobile branding."""

    VALIDATION = 8
    """Workflow graph gate, contract validator, proof pass, rules
    validator, verify trigger, blueprint writer, substrate brief."""


# --------------------------------------------------------------------------- #
# Per-run counter
# --------------------------------------------------------------------------- #

# Keyed by output_dir (each generation has its own). Value: {guard_name: count}
_run_counter: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

# Set of output_dirs where apply_post_generate_fixes has completed at least
# once in the CURRENT process. Second call for the same dir logs a warning.
_completed_runs: set[str] = set()


def reset_run(output_dir: str) -> None:
    """Clear the per-run counter for ``output_dir`` and drop it from the
    completed-runs set. Called at the start of every
    ``apply_post_generate_fixes`` invocation so re-runs (Smith edit flows,
    tests) begin from a clean slate."""
    key = _canonical(output_dir)
    _run_counter.pop(key, None)
    _completed_runs.discard(key)


def record_guard_run(
    output_dir: str,
    guard_name: str,
    phase: PostGenPhase,
) -> int:
    """Bump the counter for ``guard_name`` under ``output_dir``. Returns
    the new count. Logs a WARNING when a guard is recorded more than once
    for the same output_dir — that's the signal the suite ran a guard
    twice in one generation, which is the state Phase 7 is set up to
    detect."""
    key = _canonical(output_dir)
    slot = _run_counter[key]
    slot[guard_name] = slot.get(guard_name, 0) + 1
    count = slot[guard_name]
    if count > 1:
        logger.warning(
            "[post-gen] guard %r ran %d times in %s (phase %s) — "
            "duplicate invocation, expected exactly once per generation",
            guard_name, count, key, phase.name,
        )
    return count


def mark_run_complete(output_dir: str) -> None:
    """Called at the tail of ``apply_post_generate_fixes``. Adds
    ``output_dir`` to the completed-runs set so a subsequent call for the
    same output_dir can be detected."""
    _completed_runs.add(_canonical(output_dir))


def is_run_complete(output_dir: str) -> bool:
    """Whether ``apply_post_generate_fixes`` has already completed for
    ``output_dir`` in the current process. Used by the entry point to
    warn about duplicate top-level calls."""
    return _canonical(output_dir) in _completed_runs


def run_report(output_dir: str) -> dict[str, int]:
    """Snapshot of {guard_name: count} for ``output_dir``. Empty dict if
    no guards ran (or reset_run was called and nothing has run since).
    Useful for tests + dev-mode assertions."""
    return dict(_run_counter.get(_canonical(output_dir), {}))


def assert_guards_ran_once(output_dir: str) -> list[str]:
    """Return the list of guards that ran MORE than once. Empty list =
    every guard ran exactly once (Phase 7's target invariant). Callers
    can raise on non-empty or just log."""
    return [
        name for name, count in _run_counter.get(_canonical(output_dir), {}).items()
        if count > 1
    ]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _canonical(output_dir: Any) -> str:
    """Normalise to an absolute path so ``./out`` and ``/abs/out`` don't
    each get their own counter entry."""
    try:
        return os.path.abspath(str(output_dir))
    except Exception:
        return str(output_dir)
