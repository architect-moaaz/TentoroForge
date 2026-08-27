"""The declared state of every binary feature gate — one file to read.

Before this, answering "what is actually running?" meant grepping 96
``FORGE_*`` reads across the tree, working out each one's truthiness
convention, cross-referencing ``.env``, and knowing which ones default ON
in code rather than being listed anywhere. Nobody could do that reliably,
which is why the flags stopped being reassuring and started being noise.

``SHIPPED`` below records the state each gate has **in code, with no
configuration** — a fresh checkout with no ``.env``. That is deliberately
not the same question as "what does our deployment run": ``.env`` layers
on top, and :func:`effective` reports the combination. Keeping them apart
matters, because a checkout with no ``.env`` must not silently start
running opt-in features; the alternative (recording ``.env`` values here)
broke exactly that property for Smith and self-verify.

HOW THIS WAS DERIVED: each value is the default the gate's own code
applies when the variable is unset — detected from the truthiness test at
the read site, so ``FORGE_LANGGRAPH`` and ``FORGE_LANGGRAPH_PIPELINE``
(absent from ``.env``, ON in code) are recorded ON rather than being
silently switched off by a change that looked like pure cleanup.

SCOPE: binary on/off gates only. Config values (models, URLs, timeouts)
and multi-valued modes (``off|warn|strict``) are deliberately excluded —
they don't have a shipped-boolean and forcing them into one would lose
their semantics. ``tests/services/test_flag_manifest.py`` fails the build
if a binary gate is read in production code without being declared here,
so this file cannot silently fall behind.
"""
from __future__ import annotations

SHIPPED: dict[str, bool] = {
    'FORGE_21ST_MCP': False,                              # opt-in
    'FORGE_A11Y_GATE_STRICT': False,                      # opt-in
    'FORGE_APPROVAL_GATES': False,                        # opt-in
    'FORGE_APP_TESTS_LIVE': False,                        # opt-in
    'FORGE_AUDIT_TRAIL': False,                           # opt-in
    'FORGE_AUTOFIX_V2': False,                            # opt-in
    'FORGE_BINDING_SMOKE': False,                         # opt-in
    'FORGE_BLUEPRINT': False,                             # opt-in
    'FORGE_BRIEF_AUTHOR': False,                          # opt-in
    'FORGE_BRIEF_CANONICAL': False,                       # opt-in
    'FORGE_BRIEF_CONSUME': False,                         # opt-in
    'FORGE_CACHE_HERE__': False,                          # opt-in
    'FORGE_CAPACITY_CONSTRAINTS': False,                  # opt-in
    'FORGE_CLEANUP_WAVE_4': False,                        # opt-in
    'FORGE_COLLECTION_AUTHORITY': False,                  # opt-in
    'FORGE_COMPONENT_CATALOG_CACHE': True,                # defaults ON in code
    'FORGE_COMPOSER_VISION': False,                       # opt-in
    'FORGE_A2UI': False,                                  # opt-in
    'FORGE_A2UI_SCOPE': False,                            # opt-in
    'FORGE_BINDING_RESOLVER': True,                        # defaults ON in code
    'FORGE_COMPOSITION_RECIPES': False,                   # opt-in
    'FORGE_COVERAGE_CRITIC': False,                       # opt-in
    'FORGE_CRITIC_PANEL': False,                          # opt-in
    'FORGE_DASHBOARD_AUTHORITY': False,                   # opt-in
    'FORGE_DEFAULT_MONTAGE': False,                       # opt-in
    'FORGE_DESIGN_CONTEXT_PACK': False,                   # opt-in
    'FORGE_DETERMINISTIC_CRUD': True,                     # defaults ON in code
    'FORGE_DETERMINISTIC_WORKFLOWS': True,                # defaults ON in code
    'FORGE_EMAIL_FROM': False,                            # opt-in
    'FORGE_EMIT_APP_TESTS': True,                         # defaults ON in code
    'FORGE_E_INTERACTIONS': False,                        # opt-in
    'FORGE_E_PATTERNS': False,                            # opt-in
    'FORGE_FIELD_VISIBILITY': False,                      # opt-in
    'FORGE_FIGMA_LLM': False,                             # opt-in
    'FORGE_FIX_AGENT': False,                             # opt-in
    'FORGE_FORM_CONTEXT_PANEL': False,                    # opt-in
    'FORGE_FORM_UX_INVARIANTS': False,                    # opt-in
    'FORGE_IMMUTABILITY': False,                          # opt-in
    'FORGE_INPUT_MAP_BACKFILL': False,                    # opt-in
    'FORGE_JOURNEY_BOOT': False,                          # opt-in
    'FORGE_KEEP_DB_STATE': False,                         # opt-in
    'FORGE_LANGGRAPH': True,                              # defaults ON in code
    'FORGE_LANGGRAPH_PIPELINE': True,                     # defaults ON in code
    'FORGE_LEGACY_ANTHROPIC': False,                      # opt-in
    'FORGE_LEGACY_DESIGN_AGENT': False,                   # opt-in
    'FORGE_LIBRARY_CATALOG': False,                       # opt-in
    'FORGE_LOCKED_SPEC': False,                           # opt-in
    'FORGE_NARRATIVE_EXPANSION': False,                   # opt-in
    'FORGE_PACKAGES': False,                              # opt-in
    'FORGE_PAGE_COMPOSER': False,                         # opt-in
    'FORGE_PAGE_CONTRACT_RETRY': False,                   # opt-in
    'FORGE_PAGE_CRITIC': False,                           # opt-in
    'FORGE_PAGE_CRITIC_': False,                          # opt-in
    'FORGE_PAGE_CRITIC_REVISE': False,                    # opt-in
    'FORGE_PAGE_CRITIC_VISION': False,                    # opt-in
    'FORGE_PAGE_DESIGN_MEMORY': False,                    # opt-in
    'FORGE_PLANNER_CRITIC': False,                        # opt-in
    'FORGE_PLANNER_V2': False,                            # opt-in
    'FORGE_POLISH_': False,                               # opt-in
    'FORGE_POLISH_A11Y': False,                           # opt-in
    'FORGE_POLISH_DASHBOARD': False,                      # opt-in
    'FORGE_POLISH_EDGE_PAGES': True,                      # defaults ON in code
    'FORGE_POLISH_HIGH_CONTRAST': False,                  # opt-in
    'FORGE_POLISH_INTERACTIONS': False,                   # opt-in
    'FORGE_POLISH_LOGO': False,                           # opt-in
    'FORGE_POLISH_MOTION': False,                         # opt-in
    'FORGE_POLISH_SIGNATURE_MOVES': False,                # opt-in
    'FORGE_POLISH_VARIETY': False,                        # opt-in
    'FORGE_PRODUCT_BRIEF': False,                         # opt-in
    'FORGE_PROJECT_ID': False,                            # opt-in
    'FORGE_PURGE_CUSTOM': False,                          # opt-in
    'FORGE_RECORD_AUTHORITY': False,                      # opt-in
    'FORGE_RECOVER_LADDER': False,                        # opt-in
    'FORGE_S3_BUCKET': False,                             # opt-in
    'FORGE_S3_PREFIX': False,                             # opt-in
    'FORGE_S3_REGION': False,                             # opt-in
    'FORGE_SEED_SMOKE': False,                            # opt-in
    'FORGE_SELF_HEAL': False,                             # opt-in
    'FORGE_SELF_VERIFY': False,                           # opt-in
    'FORGE_SHELL_AUTHORITY': False,                       # opt-in
    'FORGE_SMITH': False,                                 # opt-in
    'FORGE_SMITH_ARCHITECT': True,                        # defaults ON in code
    'FORGE_SMITH_CLASSIFIER': False,                      # opt-in
    'FORGE_SMITH_ORCH': False,                            # opt-in
    'FORGE_SMITH_PLANNER_CRITIC': False,                  # opt-in
    'FORGE_SMITH_SCOPE_PREFILTER': False,                 # opt-in
    'FORGE_STRICT_PLAN': False,                           # opt-in
    'FORGE_SURFACE_TREATMENT': False,                     # opt-in
    'FORGE_USAGE_LOG': False,                             # opt-in
    'FORGE_VERIFY_AUTO': False,                           # opt-in
    'FORGE_VERIFY_CONTAINER': True,                       # defaults ON in code
    'FORGE_VERIFY_SMITH_FIX': False,                      # opt-in
    'FORGE_VISUAL_QA': False,                             # opt-in
    'FORGE_VOCAB_COMPOSER': False,                        # opt-in
    'FORGE_VOCAB_MODIFIER': False,                        # opt-in
    'FORGE_WF_PROCESS_VARS_WIRE': False,                  # opt-in
    'FORGE_WIZARD': False,                                # opt-in
    'FORGE_WORKFLOW_STRICT': False,                       # opt-in
    'FORGE_X': False,                                     # opt-in
}


def is_declared(name: str) -> bool:
    """Whether this gate has a declared shipped state."""
    return name in SHIPPED


def shipped_default(name: str, fallback: bool = False) -> bool:
    """The declared state, or ``fallback`` for an undeclared gate."""
    return SHIPPED.get(name, fallback)


def effective(env: dict[str, str] | None = None) -> dict[str, bool]:
    """What is actually on right now: declared defaults + env overrides.

    This is the "what is running?" answer. ``SHIPPED`` alone is the
    no-configuration baseline; a deployment's ``.env`` moves gates on top
    of it, and only the combination describes a real build.
    """
    import os as _os
    src = _os.environ if env is None else env
    out = dict(SHIPPED)
    for name in out:
        raw = (src.get(name) or "").strip().lower()
        if raw:
            out[name] = raw in ("1", "true", "yes", "on")
    return out


def summary() -> str:
    """One-line census — handy in a boot log or a bug report."""
    on = sum(1 for v in SHIPPED.values() if v)
    eff = sum(1 for v in effective().values() if v)
    return (f"{len(SHIPPED)} declared gates: {on} on by default, "
            f"{eff} on in this environment")
