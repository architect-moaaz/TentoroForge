"""Tests for services.vocab_ranker — multi-vocab keyword scorer.

Reuses the real ``_ARCHETYPE_KEYWORDS`` dictionary via the ranker under
test — no mocks. Verifies that hybrid domains (neobank+chat, HSA) surface
multiple vocabs in the pool so the composer has something to work with.
"""
from __future__ import annotations

from services.vocab_ranker import (
    rank_vocabs_by_keyword_hits,
    select_candidate_pool,
)


# --------------------------------------------------------------------- #
# Single-domain sanity — highest scorer is the "obvious" archetype
# --------------------------------------------------------------------- #

def test_yoga_plan_ranks_booking_platform_first():
    plan = {
        "description": "Yoga studio booking with class sessions and instructors.",
        "entities": [
            {"name": "Booking"},
            {"name": "ClassSession"},
            {"name": "Instructor"},
        ],
    }
    ranked = rank_vocabs_by_keyword_hits(plan)
    top = ranked[0]
    assert top[0] == "booking-platform"
    assert top[1] >= 2


# --------------------------------------------------------------------- #
# Hybrid domain 1 — neobank + in-app chat
# --------------------------------------------------------------------- #

def test_neobank_chat_places_banking_and_messaging_in_top3():
    plan = {
        "description": (
            "A neobank for freelancers with in-app support chat, direct "
            "message threads for customer service, workspace channels for "
            "account teams, and monthly subscription billing tiers with "
            "recurring MRR reporting. KYC compliance included."
        ),
        "entities": [
            {"name": "Account"},
            {"name": "Transaction"},
            {"name": "ChatChannel"},
            {"name": "SubscriptionTier"},
        ],
    }
    pool = select_candidate_pool(plan, max_candidates=5, min_score=2)
    assert "banking-platform" in pool[:3]
    assert "messaging-platform" in pool[:3]


# --------------------------------------------------------------------- #
# Hybrid domain 2 — HSA (health + banking)
# --------------------------------------------------------------------- #

def test_hsa_plan_places_healthcare_and_banking_in_top3():
    plan = {
        "description": (
            "A Health Savings Account platform where patients see medical "
            "bills, insurance claims, and can pay providers directly from "
            "their tax-advantaged bank accounts. Compliance and KYC required."
        ),
        "entities": [
            {"name": "Patient"},
            {"name": "Account"},
            {"name": "Claim"},
            {"name": "Prescription"},
        ],
    }
    pool = select_candidate_pool(plan, max_candidates=5, min_score=2)
    assert "healthcare-platform" in pool[:3]
    assert "banking-platform" in pool[:3]


# --------------------------------------------------------------------- #
# Empty pool when no keywords hit
# --------------------------------------------------------------------- #

def test_no_matching_keywords_returns_empty_pool():
    plan = {
        "description": "A whimsical widget for arranging pebbles by luminosity.",
        "entities": [{"name": "Pebble"}, {"name": "Luminometer"}],
    }
    pool = select_candidate_pool(plan)
    assert pool == []


# --------------------------------------------------------------------- #
# min_score guard
# --------------------------------------------------------------------- #

def test_min_score_two_filters_single_hit_matches():
    # "booking" alone is a single hit — should not clear min_score=2.
    plan = {"description": "A booking widget.", "entities": []}
    pool = select_candidate_pool(plan, min_score=2)
    assert "booking-platform" not in pool


def test_min_score_one_allows_single_hits():
    plan = {"description": "A booking widget.", "entities": []}
    pool = select_candidate_pool(plan, min_score=1)
    # With a threshold of 1, "booking" is enough to surface it.
    assert "booking-platform" in pool


# --------------------------------------------------------------------- #
# Rank order determinism — ties break alphabetically
# --------------------------------------------------------------------- #

def test_rank_returns_stable_order_for_ties():
    # Every registered slug appears exactly once, sorted deterministically.
    ranked = rank_vocabs_by_keyword_hits({"description": "", "entities": []})
    slugs = [s for s, _ in ranked]
    # All zero-scored → alphabetical.
    assert slugs == sorted(slugs)


def test_max_candidates_respected():
    plan = {
        "description": (
            "Bank credit loan compliance KYC ledger treasury deposits mortgage "
            "chat messaging channels dms threads workspace subscription billing "
            "MRR ARR recurring invoice"
        ),
    }
    pool = select_candidate_pool(plan, max_candidates=2, min_score=2)
    assert len(pool) <= 2
