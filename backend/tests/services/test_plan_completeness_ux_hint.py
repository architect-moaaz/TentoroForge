"""Spec D Wave 1 — page.ux_hint shape validator tests.

Covers ``_check_page_ux_hint_shape`` in plan_completeness_validator:
absence is legal (Wave 1 is opt-in authoring); when present, the block
must be a dict with known keys and correctly-typed values inside their
size bounds.
"""
from __future__ import annotations

from services.plan_completeness_validator import validate_plan_completeness


def _rule_msgs(plan: dict) -> list[str]:
    return [v.msg for v in validate_plan_completeness(plan)
            if v.rule == "page_ux_hint_invalid"]


def _plan_with_page(page_extra: dict) -> dict:
    """Minimal plan carrying one page + the extras under test."""
    return {
        "entities": {},
        "pages": [{"route": "/home", "name": "Home", "archetype": "static",
                   "actions": [], **page_extra}],
        "workflows": [],
    }


# ── Absence is legal ─────────────────────────────────────────────────

def test_no_ux_hint_produces_no_violation():
    plan = _plan_with_page({})
    assert _rule_msgs(plan) == []


# ── Valid shapes accepted ────────────────────────────────────────────

def test_full_valid_ux_hint_accepted():
    plan = _plan_with_page({"ux_hint": {
        "hero_fields": ["name", "role", "stage"],
        "key_widgets": ["timeline"],
        "empty_state": "No candidates yet — invite one to get started.",
        "info_hierarchy": "candidate → role → status",
    }})
    assert _rule_msgs(plan) == []


def test_partial_ux_hint_accepted():
    plan = _plan_with_page({"ux_hint": {"empty_state": "All clear."}})
    assert _rule_msgs(plan) == []


# ── Type errors flagged ──────────────────────────────────────────────

def test_ux_hint_must_be_dict():
    plan = _plan_with_page({"ux_hint": "just a string"})
    msgs = _rule_msgs(plan)
    assert len(msgs) == 1
    assert "must be a JSON object" in msgs[0]


def test_hero_fields_wrong_type_flagged():
    plan = _plan_with_page({"ux_hint": {"hero_fields": "not a list"}})
    assert any("hero_fields" in m for m in _rule_msgs(plan))


def test_key_widgets_wrong_type_flagged():
    plan = _plan_with_page({"ux_hint": {"key_widgets": [1, 2, 3]}})
    assert any("key_widgets" in m for m in _rule_msgs(plan))


def test_empty_state_wrong_type_flagged():
    plan = _plan_with_page({"ux_hint": {"empty_state": 42}})
    assert any("empty_state" in m for m in _rule_msgs(plan))


def test_info_hierarchy_wrong_type_flagged():
    plan = _plan_with_page({"ux_hint": {"info_hierarchy": ["one", "two"]}})
    assert any("info_hierarchy" in m for m in _rule_msgs(plan))


# ── Size caps enforced ───────────────────────────────────────────────

def test_hero_fields_over_six_flagged():
    plan = _plan_with_page({"ux_hint": {
        "hero_fields": [f"f{i}" for i in range(7)],
    }})
    assert any("hero_fields" in m and "max" in m for m in _rule_msgs(plan))


def test_key_widgets_over_five_flagged():
    plan = _plan_with_page({"ux_hint": {
        "key_widgets": [f"w{i}" for i in range(6)],
    }})
    assert any("key_widgets" in m and "max" in m for m in _rule_msgs(plan))


def test_empty_state_over_160_chars_flagged():
    plan = _plan_with_page({"ux_hint": {"empty_state": "x" * 161}})
    assert any("empty_state" in m and "max" in m for m in _rule_msgs(plan))


def test_info_hierarchy_over_80_chars_flagged():
    plan = _plan_with_page({"ux_hint": {"info_hierarchy": "x" * 81}})
    assert any("info_hierarchy" in m for m in _rule_msgs(plan))


# ── Unknown keys reported ────────────────────────────────────────────

def test_unknown_key_reported_but_known_ones_still_validated():
    plan = _plan_with_page({"ux_hint": {
        "hero_fields": ["ok"],
        "novel_field": "surprise",
    }})
    msgs = _rule_msgs(plan)
    # Exactly one unknown-key violation; hero_fields is fine so no other msg.
    assert len(msgs) == 1
    assert "unknown key" in msgs[0]
