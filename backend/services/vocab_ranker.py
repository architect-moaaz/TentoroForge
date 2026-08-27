"""Multi-vocab keyword scorer + candidate-pool selector — COMPOSE-1.

The single-vocab picker in :func:`services.product_brief._archetype_from_plan`
returns exactly ONE archetype slug (the first that clears the 2-hit bar).
That's the right shape for the single-vocab modifier, but composition
needs the WHOLE ranked list — a neobank-with-in-app-chat should pull
from banking + messaging + subscription-billing simultaneously.

This module reuses ``_ARCHETYPE_KEYWORDS`` verbatim (imported, never
duplicated — one keyword-source-of-truth) and returns the ranked scores.
The composer then reads the top N as its candidate pool.

Pure module — no I/O, no LLM, deterministic in (plan). Called before
any LLM step so the pool selection is auditable.
"""
from __future__ import annotations

import re
from typing import Any

from services.product_brief import _ARCHETYPE_KEYWORDS


def _haystack(plan: dict | None, requirement: str = "") -> str:
    """Lowercased concatenation of the plan fields we score against.

    Fields folded in:
      - ``plan.description`` (the user's ask)
      - ``plan.domain`` / ``plan.domain_label`` / ``plan.industry``
      - Every entity name (camelCase split so ``ClassSession`` matches
        both ``class`` and ``session`` tokens — mirrors the split used
        by :func:`services.product_brief._archetype_from_plan`).

    Missing fields become empty strings so the scorer never raises.
    """
    if not isinstance(plan, dict):
        return (requirement or "").lower()
    parts: list[str] = []
    # The requirement is the user's own statement of what the app must do
    # — it names the tiles, columns, filters and actions. Scoring without
    # it picked vocabularies off the plan's prose alone, which is how a
    # revenue-analytics ask matched on whichever archetype happened to
    # share the most substrings. Weighted by repetition so an explicit
    # requirement outvotes an incidental word in a description.
    if requirement:
        parts.extend([requirement] * 3)
    for f in ("description", "domain", "domain_label", "industry", "name",
              "problem_statement"):
        v = plan.get(f)
        if isinstance(v, str):
            parts.append(v)
    ents = plan.get("entities")
    if isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict):
                n = e.get("name") or e.get("slug")
                if isinstance(n, str):
                    parts.append(re.sub(r"([a-z])([A-Z])", r"\1_\2", n))
            elif isinstance(e, str):
                parts.append(re.sub(r"([a-z])([A-Z])", r"\1_\2", e))
    elif isinstance(ents, dict):
        for k in ents.keys():
            if isinstance(k, str):
                parts.append(re.sub(r"([a-z])([A-Z])", r"\1_\2", k))
    return " ".join(parts).lower()


def rank_vocabs_by_keyword_hits(plan: dict | None,
                                requirement: str = "") -> list[tuple[str, int]]:
    """Score every registered archetype against the plan haystack.

    Returns ``[(vocab_id, hit_count), ...]`` sorted by hit_count
    descending, with vocab_id alphabetical as the deterministic
    tie-breaker. Every registered vocab appears exactly once (score 0
    when nothing matched) — callers filter with ``min_score``.

    A "hit" is a case-insensitive substring match of a keyword against
    the haystack (same semantics as
    :func:`services.product_brief._archetype_from_plan`).
    """
    hay = _haystack(plan, requirement)
    scored: list[tuple[str, int]] = []
    for slug, keywords in _ARCHETYPE_KEYWORDS:
        if not hay:
            hits = 0
        else:
            hits = sum(1 for kw in keywords if kw in hay)
        scored.append((slug, hits))
    # Sort: hits DESC, then slug ASC for a deterministic tie-break.
    scored.sort(key=lambda t: (-t[1], t[0]))
    return scored


def select_candidate_pool(
    plan: dict | None,
    *,
    requirement: str = "",
    max_candidates: int = 5,
    min_score: int = 2,
) -> list[str]:
    """Return up to ``max_candidates`` vocab_ids with score ≥ ``min_score``.

    Preserves rank order (highest-score first). Empty list when no vocab
    crosses the threshold — callers fall back to the single-vocab path
    in that case.

    ``min_score=2`` mirrors the existing archetype picker's two-hit rule
    so the compose stack has the same "must be intentional" floor.
    """
    if max_candidates <= 0:
        return []
    ranked = rank_vocabs_by_keyword_hits(plan, requirement)
    picked: list[str] = []
    for slug, score in ranked:
        if score < min_score:
            break  # sorted DESC — nothing after this will qualify either
        picked.append(slug)
        if len(picked) >= max_candidates:
            break
    return picked


__all__ = [
    "rank_vocabs_by_keyword_hits",
    "select_candidate_pool",
]
