"""App-scale estimation + decomposition threshold (pure, no LLM).

Foundation for the large-app decomposition path (spec B2). This module answers
one question deterministically: "is this app big enough that planning should be
split into an app-map skeleton pass + per-unit detail passes?" It never calls an
LLM and never raises — callers use it as a cheap gate before the expensive path.

Two entry points:
- ``estimate_app_scale(prompt, skeleton=None)`` — best-effort entity/page counts
  from the prompt text, refined by an actual skeleton when one is available.
- ``should_decompose(prompt, skeleton=None, threshold=None)`` — the boolean gate,
  thresholded by ``FORGE_DECOMPOSE_THRESHOLD`` (default 20).
"""

from __future__ import annotations

import os
import re

# Default entity count at/above which an app is "large" and worth decomposing.
_DEFAULT_THRESHOLD = 20

# Words that strongly signal a large / enterprise-scale build even when the
# explicit entity count is only near the threshold (bias-toward-decompose).
_LARGE_HINTS = (
    "enterprise",
    "erp",
    "suite",
    "platform",
    "large-scale",
    "large scale",
    "company-wide",
    "organization-wide",
    "multi-module",
    "modules",
)

# "<N> entities / modules / models / tables / screens / pages" — the explicit,
# author-stated scale. Highest-confidence signal when present.
_EXPLICIT_COUNT_RE = re.compile(
    r"(\d+)\s*\+?\s*"
    r"(entit|module|model|table|screen|page|object|resource|domain)",
    re.IGNORECASE,
)


def _default_threshold() -> int:
    """Threshold from env (``FORGE_DECOMPOSE_THRESHOLD``), default 20. Safe."""
    try:
        return int(os.environ.get("FORGE_DECOMPOSE_THRESHOLD", str(_DEFAULT_THRESHOLD)))
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD


def _skeleton_entities(skeleton: dict | None) -> int:
    """Actual entity count from a skeleton/plan dict, tolerating both shapes
    (``data_models`` list or ``entities`` dict/list). 0 when unknown."""
    if not isinstance(skeleton, dict):
        return 0
    dm = skeleton.get("data_models")
    if isinstance(dm, list) and dm:
        return len(dm)
    ents = skeleton.get("entities")
    if isinstance(ents, dict):
        return len(ents)
    if isinstance(ents, list):
        return len(ents)
    return 0


def _skeleton_pages(skeleton: dict | None) -> int:
    if not isinstance(skeleton, dict):
        return 0
    pages = skeleton.get("pages")
    if isinstance(pages, (list, dict)):
        return len(pages)
    return 0


def _count_prompt_entities(prompt: str) -> int:
    """Best-effort entity count from free-text prompt. Never raises.

    Combines three weak signals and takes the max:
    1. Explicit "N entities/modules/..." numbers (highest confidence).
    2. Comma / "and"-separated short noun-phrase list items.
    3. A weak length-based floor (very long briefs imply more scope).
    """
    if not prompt or not isinstance(prompt, str):
        return 0

    text = prompt.strip()

    # 1. Explicit stated counts — take the largest number the author named.
    explicit = 0
    for m in _EXPLICIT_COUNT_RE.finditer(text):
        try:
            explicit = max(explicit, int(m.group(1)))
        except (TypeError, ValueError):
            continue

    # 2. Enumerated list items: split on commas and " and " / " & ", keep only
    #    short noun-phrase-like segments (<= 4 words, alphabetic). This catches
    #    "manage customers, orders, invoices, products, ..." style briefs.
    segments = re.split(r",|\band\b|&|/|\bor\b", text, flags=re.IGNORECASE)
    list_items = 0
    for seg in segments:
        s = seg.strip()
        if not s:
            continue
        words = s.split()
        if 1 <= len(words) <= 4 and any(c.isalpha() for c in s):
            list_items += 1
    # A single segment means there was no list; don't count prose as entities.
    list_count = list_items if list_items >= 3 else 0

    # 3. Weak length floor: ~1 entity per 220 chars, capped so it can nudge but
    #    never dominate. Only meaningful for very long briefs.
    length_floor = min(len(text) // 220, 12)

    return max(explicit, list_count, length_floor)


def estimate_app_scale(prompt: str, skeleton: dict | None = None) -> dict:
    """Deterministically estimate app scale from the prompt (and skeleton if
    given). Returns ``{"entities": int, "pages": int, "large": bool}``.

    When a ``skeleton`` (app-map or plan dict) is passed, its ACTUAL entity/page
    counts take precedence over the prompt heuristic. Never raises.
    """
    try:
        threshold = _default_threshold()

        actual_entities = _skeleton_entities(skeleton)
        actual_pages = _skeleton_pages(skeleton)

        prompt_entities = _count_prompt_entities(prompt)

        entities = actual_entities if actual_entities else prompt_entities
        # Pages: prefer the skeleton's real page set; else rough 1.5x entities
        # (list + detail/form per entity, minus shared dashboards).
        if actual_pages:
            pages = actual_pages
        else:
            pages = int(round(entities * 1.5)) if entities else 0

        large = entities >= threshold
        return {"entities": int(entities), "pages": int(pages), "large": bool(large)}
    except Exception:
        # Never raise — a bad estimate must not break the pipeline.
        return {"entities": 0, "pages": 0, "large": False}


def should_decompose(
    prompt: str,
    skeleton: dict | None = None,
    threshold: int | None = None,
) -> bool:
    """True when the app is large enough to warrant the app-map decomposition
    path. Thresholded by ``threshold`` or ``FORGE_DECOMPOSE_THRESHOLD`` (20).

    Biases toward True when the estimate is *near* the threshold AND the prompt
    carries enterprise-scale hints — decomposing a medium app is cheap; failing
    to decompose a large one is expensive. Never raises.
    """
    try:
        thr = threshold if isinstance(threshold, int) and threshold > 0 else _default_threshold()
        scale = estimate_app_scale(prompt, skeleton)
        entities = scale.get("entities", 0)

        if entities >= thr:
            return True

        # Bias-toward-decompose: uncertain-and-large. If the brief reads as an
        # enterprise/large build and we're already at 70%+ of the threshold,
        # decompose rather than risk a too-big single planning context.
        text = (prompt or "").lower() if isinstance(prompt, str) else ""
        if entities >= max(1, int(thr * 0.7)) and any(h in text for h in _LARGE_HINTS):
            return True

        return False
    except Exception:
        return False
