"""Slice 3 — recipe_picker heuristic tests.

The picker is a fallback for when discovery can't emit a recipe key directly.
These tests fix its behavior on realistic (persona, page_intent) inputs
drawn from the domains that motivated the library:
    - yoga studio member (member_home)
    - visual product scanner shopper (shopper_home)
    - recruitment recruiter (manager_overview)
    - time & attendance manager (manager_overview)
    - ride-hailing dispatcher (operator_console)

These are the acceptance targets — they exercise the picker's ability
to route persona vocabulary to the right recipe.
"""
from __future__ import annotations

import pytest

from services.composition.recipe_picker import pick_recipe, score_recipes


# -- fixtures across acceptance domains -------------------------------- #

CASES = [
    # (persona,           page_intent,           expected_recipe)
    ("member",            "home dashboard",      "member_home"),
    ("subscriber",        "your day",            "member_home"),
    ("shopper",           "home",                "shopper_home"),
    ("customer",          "for you",             "shopper_home"),
    ("manager",           "team overview",       "manager_overview"),
    ("lead",              "team pulse",          "manager_overview"),
    ("dispatcher",        "operations console",  "operator_console"),
    ("operator",          "ops floor now",       "operator_console"),
    ("learner",           "continue learning",   "learner_home"),
    ("student",           "continue",            "learner_home"),
    ("designer",          "workspace",           "creator_workspace"),
    ("writer",            "studio today",        "creator_workspace"),
    ("driver",            "route",               "field_worker_today"),
    ("technician",        "next job",            "field_worker_today"),
    ("analyst",           "read",                "analyst_workspace"),
    ("patron",            "on the calendar",     "patron_events"),
]


@pytest.mark.parametrize("persona,intent,expected", CASES)
def test_pick_recipe_expected_domain(persona: str, intent: str, expected: str) -> None:
    got = pick_recipe(persona, intent)
    assert got == expected, (
        f"persona={persona!r} intent={intent!r} → got {got!r}, wanted {expected!r}\n"
        f"top ranked: {score_recipes(persona, intent)[:3]}"
    )


# -- edge cases -------------------------------------------------------- #

def test_pick_recipe_none_signal_returns_none() -> None:
    assert pick_recipe(None, None) is None
    assert pick_recipe("", "") is None
    assert pick_recipe("   ", "   ") is None


def test_pick_recipe_unknown_persona_still_returns_when_intent_matches() -> None:
    # Persona junk should not block a good intent signal.
    got = pick_recipe("randomstring_xyz", "operations console dispatcher")
    assert got == "operator_console"


def test_pick_recipe_min_score_gates_weak_matches() -> None:
    # persona-only match scores 2 (weighted 2x); intent-only scores 1 per hit.
    # With min_score=5, a single-word match must be rejected.
    got = pick_recipe("member", "home", min_score=100)
    assert got is None


def test_score_recipes_is_sorted_descending() -> None:
    ranked = score_recipes("member subscriber", "your day")
    assert ranked, "expected at least one match"
    scores = [m.score for m in ranked]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0].key == "member_home"
