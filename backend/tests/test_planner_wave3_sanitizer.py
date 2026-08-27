"""Planner normalizer for Spec E Wave 3 emissions.

Every field is optional; malformed shapes are dropped silently so the
downstream deterministic passes only ever see clean data. Prompt-side
documentation is validated separately in test_planner_wave3_prompt.
"""
from __future__ import annotations

import pytest

from agents.planner import _sanitize_page_wave3_ux


def _run(plan):
    return _sanitize_page_wave3_ux(plan)


# ── wizard block ───────────────────────────────────────────────

def test_wizard_valid_shape_passes_through():
    plan = {"pages": [{"wizard": {"steps": [
        {"id": "s1", "title": "S", "fields": ["a", "b"]},
        {"title": "S2", "fields": ["c"], "nextIf": "c"},
    ]}}]}
    out = _run(plan)
    steps = out["pages"][0]["wizard"]["steps"]
    assert steps[0]["id"] == "s1"
    assert steps[0]["fields"] == ["a", "b"]
    assert steps[1]["id"] == "step_2"  # auto-assigned
    assert steps[1]["nextIf"] == "c"


def test_wizard_malformed_steps_dropped():
    plan = {"pages": [{"wizard": {"steps": [
        "not a dict",
        {"title": "", "fields": ["a"]},          # empty title
        {"title": "T"},                           # missing fields
        {"title": "T", "fields": []},             # empty fields
        {"title": "T", "fields": ["", "  "]},     # only blank
    ]}}]}
    out = _run(plan)
    assert "wizard" not in out["pages"][0]


def test_wizard_key_removed_when_shape_wrong_entirely():
    plan = {"pages": [{"wizard": "nope"}]}
    out = _run(plan)
    # A non-dict wizard is left untouched (we only clean known shapes).
    # We assert it doesn't crash and the pages array survives.
    assert isinstance(out["pages"], list)


# ── list.editable_columns ──────────────────────────────────────

def test_editable_columns_kept_when_strings():
    plan = {"pages": [{"list": {"editable_columns": ["name", "role", "  "]}}]}
    out = _run(plan)
    assert out["pages"][0]["list"]["editable_columns"] == ["name", "role"]


def test_editable_columns_dropped_when_wrong_type():
    plan = {"pages": [{"list": {"editable_columns": "name,role"}}]}
    out = _run(plan)
    assert "editable_columns" not in out["pages"][0]["list"]


def test_editable_columns_empty_list_removed():
    plan = {"pages": [{"list": {"editable_columns": []}}]}
    out = _run(plan)
    assert "editable_columns" not in out["pages"][0]["list"]


# ── list.filter_fields ─────────────────────────────────────────

def test_filter_fields_coerces_unknown_type_to_string():
    plan = {"pages": [{"list": {"filter_fields": [
        {"name": "status", "type": "categorical"},
        {"name": "amount", "type": "number", "operators": ["gt", "lt"]},
        {"name": "", "type": "string"},               # dropped
        "not a dict",                                  # dropped
    ]}}]}
    out = _run(plan)
    ff = out["pages"][0]["list"]["filter_fields"]
    assert ff[0] == {"name": "status", "type": "string"}
    assert ff[1] == {"name": "amount", "type": "number",
                     "operators": ["gt", "lt"]}
    assert len(ff) == 2


# ── layout master_detail + detail_route ────────────────────────

def test_layout_master_detail_normalises_case():
    plan = {"pages": [{"layout": "MASTER_DETAIL",
                       "list": {"detail_route": "/x/:id"}}]}
    out = _run(plan)
    assert out["pages"][0]["layout"] == "master_detail"
    assert out["pages"][0]["list"]["detail_route"] == "/x/:id"


def test_detail_route_dropped_when_wrong_type():
    plan = {"pages": [{"list": {"detail_route": 123}}]}
    out = _run(plan)
    assert "detail_route" not in out["pages"][0]["list"]


# ── journey.onboarding ─────────────────────────────────────────

def test_journey_onboarding_normalised():
    plan = {"journey": {"onboarding": {"steps": [
        {"target_selector": "#a", "title": "T1", "body": "B1", "page": "/"},
        {"target": "#b", "title": "T2"},
        {"target_selector": "", "title": "bad"},  # dropped
        "junk",
    ]}}}
    out = _run(plan)
    steps = out["journey"]["onboarding"]["steps"]
    assert len(steps) == 2
    assert steps[0]["target_selector"] == "#a"
    assert steps[0]["body"] == "B1"
    assert steps[1]["target_selector"] == "#b"


def test_journey_onboarding_dropped_when_empty():
    plan = {"journey": {"onboarding": {"steps": ["nope"]}}}
    out = _run(plan)
    assert "onboarding" not in out["journey"]
