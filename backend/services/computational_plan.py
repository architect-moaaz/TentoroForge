"""Deterministic plan builder for the `computational` archetype.

Bypasses the LLM planner when the capability gate classifies a prompt as
computational (calculator, converter, quiz-scorer, unit converter, …).

Why bypass the LLM: the general PLANNER_SYSTEM_PROMPT has MANDATORY sections
(persist actors as User entity, generate workflow_tasks, emit auth pages,
inject actors[]) that were designed for CRUD apps. Even with COMPUTATIONAL
guidance appended, the LLM often falls back to CRUD-shaped output —
inventing a `CalculationSession` entity, a `/login` page, `/visitors` CRUD
routes. For a stateless tool, that produces an app with a shell of what the
user asked for but no working core.

This module emits a canonical single-page plan with the exact shape every
downstream stage expects: entities=[], relations=[], workflows=[],
api_routes=[], one anonymous visitor actor, one page whose description IS
the user's original prompt. The page-schema author downstream sees
`archetype: "computational"` and picks up the _COMPUTATIONAL template that
teaches it to emit `interaction.computed` on the result field.

Public API:
    build_computational_plan(prompt: str, classification: dict) -> dict
"""

from __future__ import annotations

import re
from typing import Any


def _derive_name(prompt: str, classification: dict) -> str:
    """Human-readable page/app name from the prompt.

    Priority: first matched computational token ("calculator", "converter", …)
    from the classification, prefixed with 1-2 leading domain words from the
    prompt if present ("EMI calculator" from "EMI calculator app for …").
    Falls back to the raw title-cased first-three-words of the prompt.
    """
    matched = classification.get("matched") or []
    kind_word = (matched[0] if matched else "").strip()

    if kind_word:
        # Look backwards in the prompt for a 1-2 word qualifier immediately
        # before the matched token. "monthly EMI calculator" → "EMI Calculator".
        pattern = re.compile(rf"(\b\w+(?:\s+\w+)?)\s+{re.escape(kind_word)}\b", re.IGNORECASE)
        m = pattern.search(prompt)
        if m:
            qualifier = m.group(1).strip()
            # Skip generic articles/verbs so "build me a calculator" doesn't
            # become "Me A Calculator" — pick the noun-ish qualifier.
            if qualifier.lower().split()[-1] not in {"a", "an", "the", "me", "us", "my", "your", "our", "build", "make", "create"}:
                # Preserve all-caps words as-is (EMI, BMI, USD) — title() would
                # butcher them to "Emi" etc. Non-acronym words get title-cased.
                qualifier_out = " ".join(w if w.isupper() else w.title() for w in qualifier.split())
                return f"{qualifier_out} {kind_word.title()}"
        return kind_word.title()

    # Fallback: first few meaningful words from the prompt
    words = [w for w in re.findall(r"\b[A-Za-z]+\b", prompt)
             if w.lower() not in {"a", "an", "the", "build", "make", "create", "me", "us", "my", "your", "our"}]
    return " ".join(words[:3]).title() or "Tool"


def build_computational_plan(prompt: str, classification: dict | None = None) -> dict[str, Any]:
    """Return a canonical single-page plan for a computational ask.

    Shape matches what `_normalize_oneshot_plan` + `_annotate_page_types` would
    produce for an LLM-authored plan, so every downstream stage
    (`create_registry`, `build_schema_files`, page-schema author, deployment)
    is byte-identical to the LLM path — only the plan authoring changes.

    The page's `description` intentionally contains the user's ORIGINAL PROMPT
    verbatim; the downstream page-schema author reads it and (guided by the
    _COMPUTATIONAL template) translates the formula intent into
    `interaction.computed` on the result field.
    """
    classification = classification or {}
    name = _derive_name(prompt or "", classification)
    prompt_clean = (prompt or "").strip() or "(no prompt provided)"

    return {
        # Metadata — matches the shape the LLM planner emits, so downstream
        # normalizers pass through unchanged.
        "meta": {
            "source": "computational_plan_builder",
            "archetype": "computational",
            "matched_tokens": list(classification.get("matched") or []),
        },

        # No persistence — the whole point of the archetype.
        "entities": [],
        "relations": [],
        "workflows": [],
        "api_routes": [],

        # One anonymous visitor — no signup, no login, no accounts.
        # `access: "anon"` tells the shell/auth-emitters not to insert
        # login/signup pages or middleware.
        "actors": [
            {
                "name": "visitor",
                "access": "anon",
                "onboarding": "none",
                "description": "Anonymous user of this standalone tool.",
            }
        ],

        # Single page — archetype tells the schema author to use the
        # _COMPUTATIONAL template. Description carries the user's original
        # prompt so the LLM has the full formula intent to translate.
        "pages": [
            {
                "route": "/",
                "name": name,
                "archetype": "computational",
                "features": [],
                "description": prompt_clean,
                "shell": True,
            }
        ],

        # Empty top-level slots the pipeline expects — must be present so
        # downstream `.get("...", [])` calls don't have to guard for None.
        "components": [],
        "structured_brief": None,
        "dashboard_widgets": [],
        "field_visibility": [],
        "capacity_constraints": [],

        # Nav — one page, one entry. The shell composer reads this.
        "navigation": {
            "type": "none",  # No sidebar/topbar chrome — the whole viewport IS the tool.
            "initial": "/",
            "items": [],
        },
    }


def is_computational_classification(classification: dict | None) -> bool:
    """True iff the capability gate marked this as a computational ask.

    Router intercepts on this before spinning up the LLM planner.
    """
    if not isinstance(classification, dict):
        return False
    return classification.get("shape") == "computational"
