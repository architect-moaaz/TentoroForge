"""Token completeness guard — backfill design token subtrees that library
components read at runtime.

Motivation
----------
Library components ship with implicit contracts about the token shape they'll
read at render time (e.g. ``tokens.typography.numeric.family`` in
``MetricTile``). When the design agent's LLM output for ``design-spec.json``
omits or empties a subtree the compiler is supposed to fill, the compiled
token bundle ends up missing keys the library dereferences unconditionally —
and every generated page that uses one of those components throws an SSR
error like the one in bug B-020.8:

    "An error occurred in the Server Components render. The specific message
    is omitted in production builds…"

The failure is asymmetric: on the design side we *should* always populate
these subtrees (``design_compiler.py`` does so today), but ``design-spec.json``
can also carry a partial override from downstream refinement, and app-level
``tokens.custom.json`` files edited via the visual editor can strip keys
outright. Rather than chase every path, this guard runs after all generation
+ refinement steps and reads the two files that actually feed
``@tentoroforge/library``'s ``useTokens()`` — ``design-spec.json`` and
``theme/tokens.custom.json`` — filling any subtree the library reads.

Scope
-----
Only fills subtrees a **library component** reads at render time. Subtree
values that are cosmetic (font families, shadow blur radius) get a
conservative default that matches ``defaultTokens`` in the library. Any key
already present is preserved untouched — this guard is additive.

Wired into ``post_generate_fixes.apply_post_generate_fixes``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Sentinel used when a token subtree is missing or non-dict. Values match the
# library's ``defaultTokens`` so the fallback renders identically to a spec
# that never touched the key.
_DEFAULT_NUMERIC = {
    "family": "Inter, system-ui, sans-serif",
    "tabular": True,
}
_DEFAULT_DISPLAY = {
    "family": "Inter, system-ui, sans-serif",
    "weight": 700,
}
_DEFAULT_BODY_TEXT = {
    "family": "Inter, system-ui, sans-serif",
    "weight": 400,
    "lineHeight": 1.5,
}
_DEFAULT_SEMANTIC_SPACING = {
    "page": "2rem",
    "card": "1.25rem",
    "section": "4rem",
    "element": "1rem",
    "input": "0.75rem",
}

# Numeric spacing scale — Cluster (and any schema `tokens.spacing.N` ref)
# resolves through `var(--token-spacing-N)` INLINE, so a missing key doesn't
# just lose the value: the invalid var() wins the cascade over stylesheet
# gaps and collapses to `gap: normal`. Live symptom (cwx1stzz): every filter
# toolbar rendered its controls fused edge-to-edge. Tailwind-compatible rems.
_DEFAULT_NUMERIC_SPACING = {
    "0": "0px", "1": "0.25rem", "2": "0.5rem", "3": "0.75rem",
    "4": "1rem", "5": "1.25rem", "6": "1.5rem", "8": "2rem",
    "10": "2.5rem", "12": "3rem", "16": "4rem",
}


def _ensure_dict(parent: dict, key: str) -> dict:
    """Return parent[key] as a dict, creating it if it was missing/non-dict.

    Non-dict values (an empty list, a string, None) are replaced with a
    fresh empty dict because the library keys into these subtrees with
    property access — an array or string there is the same crash as
    undefined.
    """
    v = parent.get(key)
    if not isinstance(v, dict):
        parent[key] = {}
    return parent[key]


def _fill_defaults(target: dict, defaults: dict) -> int:
    """Copy any key from ``defaults`` that ``target`` doesn't already have.

    Returns the number of keys added. Existing keys are preserved even if
    their value looks empty — the guard only fills genuinely-absent keys.
    """
    added = 0
    for k, v in defaults.items():
        if k not in target:
            target[k] = v
            added += 1
    return added


def ensure_token_completeness(tokens_or_spec: dict) -> int:
    """Fill the token subtrees library components read unconditionally.

    ``tokens_or_spec`` is mutated in place. Works on both raw
    ``design-spec.json`` shapes (which nest under ``typography``,
    ``spacing`` at the top) and compiled token bundles — the schema is
    identical for the subset we touch.

    Returns the number of key-level backfills applied (0 if the input was
    already complete).
    """
    if not isinstance(tokens_or_spec, dict):
        return 0

    added = 0

    # Typography — MetricTile reads .typography.numeric.family +
    # .typography.numeric.tabular. Stat / Chart read display + bodyText.
    typography = _ensure_dict(tokens_or_spec, "typography")
    numeric = _ensure_dict(typography, "numeric")
    added += _fill_defaults(numeric, _DEFAULT_NUMERIC)
    display = _ensure_dict(typography, "display")
    added += _fill_defaults(display, _DEFAULT_DISPLAY)
    body_text = _ensure_dict(typography, "bodyText")
    added += _fill_defaults(body_text, _DEFAULT_BODY_TEXT)

    # Spacing.semantic — Card/Stack/Section deref .spacing.semantic.card etc.
    # A missing semantic subtree crashes any Card-wrapping layout.
    spacing = _ensure_dict(tokens_or_spec, "spacing")
    semantic = _ensure_dict(spacing, "semantic")
    added += _fill_defaults(semantic, _DEFAULT_SEMANTIC_SPACING)
    added += _fill_defaults(spacing, _DEFAULT_NUMERIC_SPACING)

    return added


def _apply_to_file(path: Path) -> int:
    """Load JSON, run ``ensure_token_completeness``, write back if changed.

    Silent no-op when the file doesn't exist (guard is idempotent + tolerant
    of app layouts that don't ship every possible token file).
    """
    if not path.is_file():
        return 0
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("token_completeness_guard: skipping unreadable %s: %s", path, e)
        return 0
    if not isinstance(data, dict):
        return 0
    added = ensure_token_completeness(data)
    if added > 0:
        # Preserve the file's original formatting shape (2-space indent) —
        # matches what design_compiler emits, so a diff shows only the new
        # keys, not indentation churn.
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return added


# Files the library actually reads at runtime. Ordered by how much the
# platform owns each one — design-spec is generation output; tokens.custom is
# user/editor edits that we still want to backfill for library safety.
_TARGET_FILES = (
    "src/contracts/design-spec.json",
    "contracts/design-spec.json",  # older layouts pre-move
    "src/theme/tokens.custom.json",
)


def apply_token_completeness_guard(output_dir: str | Path) -> dict[str, Any]:
    """Public entry point — runs the guard across every known token file
    under ``output_dir``. Returns a small report the guard-suite logger
    consumes.
    """
    root = Path(output_dir)
    report: dict[str, Any] = {"files_touched": [], "total_keys_added": 0}
    if not root.is_dir():
        return report
    for rel in _TARGET_FILES:
        p = root / rel
        added = _apply_to_file(p)
        if added > 0:
            report["files_touched"].append(rel)
            report["total_keys_added"] += added
    return report
