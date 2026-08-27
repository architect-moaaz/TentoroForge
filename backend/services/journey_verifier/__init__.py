"""Journey Verifier — domain-agnostic post-generation verification.

Given any generated app under `output/<slug>/`, this package:

  1. Reads `plan.json` (extractor.py)
  2. Synthesizes a JourneySpec — archetype-aware if the plan declares one,
     generic smoke test otherwise (spec.py, extractor.py)
  3. Copies fixtures into the app (fixtures.py)
  4. Emits a data-driven Playwright test file + config (emitter.py)
  5. Runs Playwright against the running app (harness.py)
  6. Returns a SuiteResult the pipeline can gate on (harness.py)

The Playwright driver is one file that dispatches on `step.kind` — the
same driver works for a recruitment app, an e-commerce app, or the
visual-product-search app. Domain-specificity lives in the JourneySpec,
not the runner. That's what makes this cheap to add archetypes to.
"""
from .spec import (
    EntityFilter,
    Journey,
    JourneySpec,
    Locator,
    Step,
    WorkflowFilter,
)
from .extractor import extract
from .emitter import emit
from .fixtures import BUILTIN_FIXTURES, collect_needed_slugs, resolve_fixtures
from .harness import JourneyResult, SuiteResult, ensure_playwright, run_journey_suite


def verify_app(output_dir, *, base_url="http://localhost:3000",
               boot_timeout_s=30, repo_root=None):
    """End-to-end: extract → emit → run → return SuiteResult.

    Called from the pipeline in warn mode (log the result, don't block) or
    strict mode (raise on failure). Same function for both — the gate
    decision lives at the caller.
    """
    from pathlib import Path

    output_dir = Path(output_dir)
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]

    spec = extract(output_dir, base_url=base_url)
    slugs = collect_needed_slugs(spec)
    spec.fixtures = resolve_fixtures(slugs, output_dir, repo_root)
    emit(spec, output_dir)
    # Route sweep rides the same Playwright invocation (config testMatch
    # includes sweep.spec.ts). Best-effort — a sweep-emission failure must
    # never take the journey gate down with it.
    try:
        from .sweep import emit_sweep
        emit_sweep(output_dir)
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("sweep emission failed: %s", exc)
    return run_journey_suite(
        output_dir,
        base_url=base_url,
        boot_timeout_s=boot_timeout_s,
        playwright_cwd=repo_root,
    )


__all__ = [
    "EntityFilter", "Journey", "JourneySpec", "Locator", "Step", "WorkflowFilter",
    "JourneyResult", "SuiteResult",
    "extract", "emit",
    "BUILTIN_FIXTURES", "collect_needed_slugs", "resolve_fixtures",
    "ensure_playwright", "run_journey_suite",
    "verify_app",
]
