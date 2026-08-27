"""Tests for services.vocab_modifier — Level 2 vocabulary modifier.

The LLM seam is exercised by monkeypatching ``_call_llm`` — we don't want
CI to depend on Anthropic being reachable. Merge + validate logic runs
against the real ``banking_platform`` vocab so the invariants are
enforced against production-shaped data.
"""
from __future__ import annotations

import asyncio

import pytest

from services import vocab_modifier
from services.archetype_vocabulary import (
    ComponentPreference,
    load_vocabulary,
)
from services.vocab_modifier import modify_vocab


def _run(coro):
    # Fresh loop per call: keeps us independent of whatever earlier tests
    # in the sweep did to the thread's default loop (some close it).
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _plan() -> dict:
    return {
        "description": "Community credit union loan origination for gig-economy borrowers.",
        "entities": [
            {"name": "Application", "columns": ["applicantName", "amount", "status"]},
            {"name": "Borrower", "columns": ["name", "employmentType"]},
            {"name": "Disbursement", "columns": ["amount", "postedAt"]},
        ],
        "actors": [
            {"role": "member"},
            {"role": "loan_officer"},
            {"role": "compliance"},
        ],
    }


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    """Every test starts with a clean in-process LRU."""
    vocab_modifier._reset_cache_for_tests()
    # Guarantee no accidental network calls.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    yield
    vocab_modifier._reset_cache_for_tests()


# --------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------- #

def test_happy_path_merges_llm_additions_and_preserves_base(monkeypatch):
    base = load_vocabulary("banking-platform")
    assert base is not None

    async def fake_llm(_prompt, *, model, timeout_s):
        # LLM adds a new persona + refines an empty-state; leaves everything
        # else alone.
        return {
            "primary_screens_per_persona": {
                "gig_borrower": ["applications", "transfers", "cards"],
            },
            "signature_states": {
                "empty_applications": "No applications yet. Start one to get a decision in minutes.",
            },
        }

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    modified, prov = _run(modify_vocab(base, _plan()))

    assert prov["source"] == "modified"
    assert "gig_borrower" in prov["changes"]["personas_added"]
    # New persona landed.
    assert modified.primary_screens_per_persona["gig_borrower"] == [
        "applications", "transfers", "cards",
    ]
    # Existing persona preserved.
    assert modified.primary_screens_per_persona["member"] == \
        base.primary_screens_per_persona["member"]
    # Refined copy landed; other empty states untouched.
    assert modified.signature_states["empty_applications"].startswith("No applications yet.")
    assert modified.signature_states["empty_cards"] == base.signature_states["empty_cards"]
    # component_preferences untouched.
    assert modified.component_preferences == base.component_preferences


def test_merge_preserves_base_when_llm_emits_only_one_field(monkeypatch):
    """LLM returns only signature_states — everything else survives verbatim."""
    base = load_vocabulary("banking-platform")

    async def fake_llm(_prompt, *, model, timeout_s):
        return {"signature_states": {"empty_transactions": "Custom copy."}}

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    modified, prov = _run(modify_vocab(base, _plan()))
    assert prov["source"] == "modified"
    assert modified.signature_states["empty_transactions"] == "Custom copy."
    assert modified.primary_screens_per_persona == base.primary_screens_per_persona
    assert modified.section_recipes == base.section_recipes
    assert modified.component_preferences == base.component_preferences
    assert modified.status_badges == base.status_badges
    assert modified.section_filters == base.section_filters


# --------------------------------------------------------------------- #
# Shape validation
# --------------------------------------------------------------------- #

def test_invalid_shape_dropped_base_preserved(monkeypatch):
    base = load_vocabulary("banking-platform")

    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "component_preferences": {
                # Bogus shape — must be dropped.
                "loans": {"shape": "custom-view", "primary_field": "borrower"},
                # Valid new entry — must land.
                "disbursements": {"shape": "ledger-list", "primary_field": "amount"},
            }
        }

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    modified, prov = _run(modify_vocab(base, _plan()))
    assert prov["source"] == "modified"
    # Bogus shape rejected; base's transactions entry untouched.
    rejected = " ".join(prov["changes"]["shapes_rejected"])
    assert "loans" in rejected and "custom-view" in rejected
    assert "loans" not in modified.component_preferences
    # Valid entry landed.
    disbursement = modified.component_preferences["disbursements"]
    assert disbursement.shape == "ledger-list"
    assert disbursement.primary_field == "amount"


# --------------------------------------------------------------------- #
# Badge variant validation
# --------------------------------------------------------------------- #

def test_invalid_badge_variant_dropped_base_preserved(monkeypatch):
    base = load_vocabulary("banking-platform")

    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "status_badges": {
                # Bogus variant — must be dropped, base's "pending" survives.
                "pending": {"variant": "info", "label": "Pending"},
                # Valid new status.
                "gig_verified": {"variant": "accent", "label": "Gig verified"},
            }
        }

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    modified, prov = _run(modify_vocab(base, _plan()))
    assert prov["source"] == "modified"
    # Base's pending untouched.
    assert modified.status_badges["pending"] == base.status_badges["pending"]
    # Warning logged for the invalid entry.
    warnings = " ".join(prov["changes"]["warnings"])
    assert "pending" in warnings and "info" in warnings
    # Valid new badge landed.
    assert modified.status_badges["gig_verified"]["variant"] == "accent"


# --------------------------------------------------------------------- #
# Section invariant enforcement
# --------------------------------------------------------------------- #

def test_section_without_empty_state_or_filter_dropped(monkeypatch):
    base = load_vocabulary("banking-platform")

    async def fake_llm(_prompt, *, model, timeout_s):
        # LLM proposes a "drafts" section but forgets both the filter
        # AND the signature_states["empty_drafts"] entry.
        return {"section_recipes": {"invoices": ["drafts", "sent"]}}

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    modified, prov = _run(modify_vocab(base, _plan()))
    assert prov["source"] == "modified"
    # Section dropped — invoices key never gets any of the invalid sections,
    # so it doesn't appear at all.
    assert "invoices" not in modified.section_recipes
    warnings = " ".join(prov["changes"]["warnings"])
    assert "drafts" in warnings
    assert "sent" in warnings


def test_section_with_matching_filter_and_empty_state_lands(monkeypatch):
    base = load_vocabulary("banking-platform")

    async def fake_llm(_prompt, *, model, timeout_s):
        # LLM proposes a full triple — recipe + filter + empty state.
        return {
            "section_recipes": {"payouts": ["scheduled", "sent"]},
            "section_filters": {
                "scheduled": {"status": ["scheduled", "queued"]},
                "sent": {"status": ["sent", "completed"]},
            },
            "signature_states": {
                "empty_scheduled": "No scheduled payouts.",
                "empty_sent": "No sent payouts yet.",
            },
        }

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    modified, prov = _run(modify_vocab(base, _plan()))
    assert prov["source"] == "modified"
    assert modified.section_recipes["payouts"] == ["scheduled", "sent"]
    assert "payouts:scheduled" in prov["changes"]["sections_added"]
    assert "payouts:sent" in prov["changes"]["sections_added"]


# --------------------------------------------------------------------- #
# Fail-open
# --------------------------------------------------------------------- #

def test_fail_open_on_timeout(monkeypatch):
    base = load_vocabulary("banking-platform")

    async def fake_llm(_prompt, *, model, timeout_s):
        raise asyncio.TimeoutError("simulated timeout")

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    result, prov = _run(modify_vocab(base, _plan()))
    assert result is base
    assert prov["source"] == "base_fallback"
    assert "timeout" in prov["reason"].lower()


def test_fail_open_on_unparseable_json(monkeypatch):
    base = load_vocabulary("banking-platform")

    async def fake_llm(_prompt, *, model, timeout_s):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    result, prov = _run(modify_vocab(base, _plan()))
    assert result is base
    assert prov["source"] == "base_fallback"


def test_fail_open_on_non_dict_llm_output(monkeypatch):
    base = load_vocabulary("banking-platform")

    async def fake_llm(_prompt, *, model, timeout_s):
        return ["not", "a", "dict"]

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    result, prov = _run(modify_vocab(base, _plan()))
    assert result is base
    assert prov["source"] == "base_fallback"


# --------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------- #

def test_cache_returns_after_first_call(monkeypatch):
    base = load_vocabulary("banking-platform")
    call_count = {"n": 0}

    async def fake_llm(_prompt, *, model, timeout_s):
        call_count["n"] += 1
        return {"signature_states": {"empty_transactions": "cached copy"}}

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    plan = _plan()
    v1, prov1 = _run(modify_vocab(base, plan))
    v2, prov2 = _run(modify_vocab(base, plan))
    assert call_count["n"] == 1
    assert prov1["source"] == "modified"
    assert prov2["source"] == "cached"
    # Same vocab object semantically.
    assert v2.signature_states["empty_transactions"] == "cached copy"


def test_cache_key_differs_on_plan_change(monkeypatch):
    base = load_vocabulary("banking-platform")
    call_count = {"n": 0}

    async def fake_llm(_prompt, *, model, timeout_s):
        call_count["n"] += 1
        return {}

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    plan_a = _plan()
    plan_b = dict(_plan())
    plan_b["description"] = "Different ask entirely."
    _run(modify_vocab(base, plan_a))
    _run(modify_vocab(base, plan_b))
    assert call_count["n"] == 2
