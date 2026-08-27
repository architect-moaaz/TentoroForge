"""Recipe selection heuristic (Slice 3).

Given a discovery persona label and a page intent (name/slug/purpose),
pick the best-fit recipe key from `recipes.json` — or return None if
no recipe scores above the confidence floor. Deliberately simple: the
authoritative signal comes from Discovery when it can emit recipes
directly; this helper is the fallback + the test surface.

The pipeline consumes recipes as follows:
    DesignBrief.page_recipes["/dashboard"] = "member_home"
    → deterministic page builder loads recipe.anchors[]
    → each anchor resolves to a registered library component

No LLM call. No fuzzy matching library. Just word-overlap scoring so
tests are deterministic and the pipeline can run offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .loader import Recipe, load_library


_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(_WORD.findall(text.lower()))


@dataclass(frozen=True)
class RecipeMatch:
    """A ranked candidate. `score` is unnormalized token-overlap count."""
    key: str
    score: int
    recipe: Recipe


def score_recipes(
    persona: str | None,
    page_intent: str | None,
) -> list[RecipeMatch]:
    """Return every recipe with score>0, sorted highest first."""
    lib = load_library()
    persona_tokens = _tokens(persona)
    intent_tokens = _tokens(page_intent)
    if not persona_tokens and not intent_tokens:
        return []

    out: list[RecipeMatch] = []
    for key, recipe in lib.recipes.items():
        persona_hits = 0
        for p in recipe.personas:
            persona_hits += len(persona_tokens & _tokens(p))
        # `label` + `purpose` describe the page intent — score both.
        intent_hits = len(intent_tokens & _tokens(recipe.label))
        intent_hits += len(intent_tokens & _tokens(recipe.purpose))
        # Category id often mirrors intent word (home/list/detail/form/…).
        intent_hits += len(intent_tokens & _tokens(recipe.category))
        # Weight persona 2x — a member on a list page still wants the member
        # experience; a manager on a form still wants the manager framing.
        score = persona_hits * 2 + intent_hits
        if score > 0:
            out.append(RecipeMatch(key=key, score=score, recipe=recipe))
    out.sort(key=lambda m: (-m.score, m.key))
    return out


def pick_recipe(
    persona: str | None,
    page_intent: str | None,
    min_score: int = 1,
) -> str | None:
    """Best recipe key for (persona, page_intent), or None if nothing scores.

    `min_score` gates weak matches — persona-only hits score 2, so the default
    of 1 lets any signal through. Raise it for stricter callers.
    """
    ranked = score_recipes(persona, page_intent)
    if not ranked:
        return None
    top = ranked[0]
    if top.score < min_score:
        return None
    return top.key


__all__ = ["RecipeMatch", "pick_recipe", "score_recipes"]
