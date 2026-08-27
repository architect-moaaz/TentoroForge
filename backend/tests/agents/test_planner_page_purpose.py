"""Sprint 4 tests — planner `_sanitize_page_purpose` + DCP passthrough.

Purpose + reading_priority are first-class planner fields as of Sprint 4.
Tests here cover:
  · sanitizer normalization (strip / length-cap / drop malformed)
  · DCP `_page_purpose_block` passthrough when planner-authored
  · DCP fallback synthesis when planner is silent
"""
from __future__ import annotations

from agents.planner import _sanitize_page_purpose
from services.design_context_pack import _page_purpose_block


# ── Sanitizer ───────────────────────────────────────────────────────────

def test_sanitizer_passes_through_valid_purpose():
    plan = {"pages": [{
        "route": "/dashboard",
        "purpose": "Help the manager see collection health this month.",
    }]}
    result = _sanitize_page_purpose(plan)
    assert result["pages"][0]["purpose"] == (
        "Help the manager see collection health this month."
    )


def test_sanitizer_trims_whitespace():
    plan = {"pages": [{"purpose": "  a purpose  \n  "}]}
    result = _sanitize_page_purpose(plan)
    assert result["pages"][0]["purpose"] == "a purpose"


def test_sanitizer_drops_empty_purpose():
    plan = {"pages": [{"purpose": "   "}]}
    result = _sanitize_page_purpose(plan)
    assert "purpose" not in result["pages"][0]


def test_sanitizer_drops_wrong_type_purpose():
    plan = {"pages": [{"purpose": {"description": "not a string"}}]}
    result = _sanitize_page_purpose(plan)
    assert "purpose" not in result["pages"][0]


def test_sanitizer_caps_long_purpose():
    long = "x" * 500
    plan = {"pages": [{"purpose": long}]}
    result = _sanitize_page_purpose(plan)
    # Result is capped at 240 chars with an ellipsis marker.
    assert len(result["pages"][0]["purpose"]) <= 240
    assert result["pages"][0]["purpose"].endswith("…")


def test_sanitizer_passes_through_reading_priority():
    plan = {"pages": [{"reading_priority": [
        "Collection status this month",
        "The one overdue payment",
        "Recent activity",
    ]}]}
    result = _sanitize_page_purpose(plan)
    assert result["pages"][0]["reading_priority"] == [
        "Collection status this month",
        "The one overdue payment",
        "Recent activity",
    ]


def test_sanitizer_caps_reading_priority_list_length():
    plan = {"pages": [{"reading_priority": ["a", "b", "c", "d", "e", "f"]}]}
    result = _sanitize_page_purpose(plan)
    # Cap = 4 items.
    assert len(result["pages"][0]["reading_priority"]) == 4
    assert result["pages"][0]["reading_priority"] == ["a", "b", "c", "d"]


def test_sanitizer_drops_empty_reading_priority():
    plan = {"pages": [{"reading_priority": ["", "  "]}]}
    result = _sanitize_page_purpose(plan)
    assert "reading_priority" not in result["pages"][0]


def test_sanitizer_drops_non_list_reading_priority():
    plan = {"pages": [{"reading_priority": "not a list"}]}
    result = _sanitize_page_purpose(plan)
    assert "reading_priority" not in result["pages"][0]


def test_sanitizer_caps_individual_item_length():
    long_item = "x" * 200
    plan = {"pages": [{"reading_priority": [long_item]}]}
    result = _sanitize_page_purpose(plan)
    # Each item capped at 80 chars.
    assert len(result["pages"][0]["reading_priority"][0]) <= 80


def test_sanitizer_handles_missing_pages():
    """Malformed plans don't crash the sanitizer."""
    assert _sanitize_page_purpose({}) == {}
    assert _sanitize_page_purpose({"pages": None}) == {"pages": None}


def test_sanitizer_skips_non_dict_pages():
    plan = {"pages": ["not a dict", 42, None]}
    # Doesn't raise; pages left as-is (skip filter).
    result = _sanitize_page_purpose(plan)
    assert result["pages"] == ["not a dict", 42, None]


# ── DCP passthrough behavior ────────────────────────────────────────────

def test_dcp_uses_planner_authored_purpose_when_present():
    plan = {"actors": []}
    page = {
        "type": "dashboard",
        "name": "Ops",
        "route": "/ops",
        "purpose": "Help the manager see collection health this month.",
        "reading_priority": ["Collection status", "One overdue", "Activity"],
    }
    block = _page_purpose_block(plan, page)
    assert "Help the manager see collection health this month." in block
    # Planner-authored priorities are enumerated in order.
    assert "1. Collection status" in block
    assert "2. One overdue" in block
    assert "3. Activity" in block
    # Source tag reflects the choice.
    assert 'source="planner-authored"' in block


def test_dcp_falls_back_to_synthesis_when_planner_silent():
    plan = {"actors": [{"name": "Manager"}]}
    page = {
        "type": "dashboard",
        "name": "Ops",
        "route": "/ops",
        "entity": "Payment",
    }
    block = _page_purpose_block(plan, page)
    # No planner-authored purpose → synthesis fires.
    assert 'source="synthesized"' in block
    # Synthesis mentions the entity.
    assert "Payment" in block


def test_dcp_synthesizes_when_planner_purpose_is_empty_string():
    """Empty planner purpose (sanitizer should have dropped it, but
    defense-in-depth: DCP still falls back if it somehow reaches us)."""
    plan = {"actors": []}
    page = {"type": "dashboard", "name": "Ops", "purpose": "   "}
    block = _page_purpose_block(plan, page)
    assert 'source="synthesized"' in block
