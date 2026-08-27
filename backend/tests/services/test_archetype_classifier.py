"""Tests for services.archetype_classifier.

The LLM path is exercised by monkeypatching _call_llm — we don't want CI
to depend on Anthropic being reachable. Deterministic fallback is tested
against the real keyword classifier.
"""
from __future__ import annotations

import asyncio

import pytest

from services import archetype_classifier
from services.archetype_classifier import (
    ArchetypeMatch,
    classify_app_archetype,
)


VISUAL_PRODUCT_SEARCH = (
    "Mobile-first app where a user scans a product with their phone camera "
    "or uploads an image. The app identifies the exact or similar-looking "
    "product using AI, then shows price comparison across retailers using "
    "the Firecrawl web-search MCP with tappable links to each seller. "
    "Admin can control the retailer allow-list (enable/disable, priority). "
    "Store scan history per user."
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------- deterministic fallback (LLM disabled) --------------------------

@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    """Guarantee tests never hit the network — remove the API key by default."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_classify_empty_description_returns_none():
    match = _run(classify_app_archetype(""))
    assert match.archetype is None
    assert match.confidence == 0.0


def test_classify_deterministic_hits_visual_product_search():
    match = _run(classify_app_archetype(VISUAL_PRODUCT_SEARCH))
    assert match.archetype == "visual-product-search"
    assert match.source == "deterministic"
    # Deterministic confidence is baked at 0.7 when keyword classifier hits.
    assert match.confidence > 0.5


def test_classify_todo_returns_none_deterministically():
    match = _run(classify_app_archetype("A tiny todo app for tasks and reminders."))
    assert match.archetype is None
    assert match.source == "deterministic"


# ---------- LLM path (mocked _call_llm) ------------------------------------

def test_llm_refines_pick_and_renames(monkeypatch):
    """When the LLM returns a valid classification, that wins over the
    deterministic baseline and the renames come along for downstream use."""
    async def fake_llm(_desc):
        return {
            "archetype": "visual-product-search",
            "confidence": 0.95,
            "renames": {"Scan": "ArtworkScan", "Retailer": "Marketplace"},
            "extra_entities": [{"name": "Artist", "kind": "entity"}],
            "reason": "art print scanner + marketplace",
        }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(archetype_classifier, "_call_llm", fake_llm)

    match = _run(classify_app_archetype(
        "Scanner for art prints that finds prices across online galleries."
    ))
    assert match.archetype == "visual-product-search"
    assert match.confidence == 0.95
    assert match.renames == {"Scan": "ArtworkScan", "Retailer": "Marketplace"}
    assert match.extra_entities == [{"name": "Artist", "kind": "entity"}]
    assert match.source == "llm"


def test_llm_hallucinated_archetype_rejected(monkeypatch):
    """The LLM returns an archetype name that isn't in the library. We must
    NOT propagate it downstream — fall back to the deterministic pick."""
    async def fake_llm(_desc):
        return {
            "archetype": "flying-cars",
            "confidence": 0.9,
            "renames": {},
            "extra_entities": [],
            "reason": "invented",
        }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(archetype_classifier, "_call_llm", fake_llm)

    match = _run(classify_app_archetype(VISUAL_PRODUCT_SEARCH))
    # LLM's archetype was None-ified by _validate_llm_result → fell back to
    # the deterministic pick's name.
    assert match.archetype == "visual-product-search"
    assert match.source == "llm-fallback"


def test_llm_returns_none_falls_back_to_deterministic(monkeypatch):
    """When _call_llm returns None (SDK missing or call failed), the
    deterministic baseline stands."""
    async def fake_llm(_desc):
        return None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(archetype_classifier, "_call_llm", fake_llm)

    match = _run(classify_app_archetype(VISUAL_PRODUCT_SEARCH))
    assert match.archetype == "visual-product-search"
    assert match.source == "deterministic"


def test_llm_bad_confidence_clamped(monkeypatch):
    async def fake_llm(_desc):
        return {
            "archetype": "visual-product-search",
            "confidence": 5.0,  # nonsense
            "renames": {},
            "extra_entities": [],
            "reason": "",
        }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(archetype_classifier, "_call_llm", fake_llm)

    match = _run(classify_app_archetype(VISUAL_PRODUCT_SEARCH))
    assert 0.0 <= match.confidence <= 1.0


def test_llm_rejects_extra_entities_with_bad_kind(monkeypatch):
    """extra_entities with a kind outside the enum are dropped."""
    async def fake_llm(_desc):
        return {
            "archetype": "visual-product-search",
            "confidence": 0.8,
            "renames": {},
            "extra_entities": [
                {"name": "Ok", "kind": "entity"},
                {"name": "Bad", "kind": "invented"},
                {"name": "Also Ok", "kind": "event"},
                {"name": "MissingKind"},
            ],
            "reason": "",
        }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(archetype_classifier, "_call_llm", fake_llm)

    match = _run(classify_app_archetype(VISUAL_PRODUCT_SEARCH))
    kinds = {e["kind"] for e in match.extra_entities}
    names = {e["name"] for e in match.extra_entities}
    assert "invented" not in kinds
    assert "MissingKind" not in names
    assert names == {"Ok", "Also Ok"}


# ---------- ArchetypeMatch serialization ----------------------------------

def test_archetype_match_to_dict():
    m = ArchetypeMatch(archetype="x", confidence=0.5, renames={"a": "b"})
    d = m.to_dict()
    assert d["archetype"] == "x"
    assert d["confidence"] == 0.5
    assert d["renames"] == {"a": "b"}
    assert d["source"] == "deterministic"
