"""field_visibility_wire — the third wire-pass primitive."""
from __future__ import annotations

import copy

import pytest

from services.field_visibility_wire import (
    is_field_visibility_enabled,
    wire_field_visibility,
)


# ── no-op paths ────────────────────────────────────────────────

def test_no_declaration_is_no_op():
    plan = {"entities": [{"name": "X"}]}
    assert wire_field_visibility(plan) == plan


def test_none_plan_returns_verbatim():
    assert wire_field_visibility(None) is None


def test_malformed_entries_dropped():
    plan = {
        "field_visibility": [
            "not a dict",
            {"entity": "X"},                # missing field
            {"field": "y"},                 # missing entity
            {"entity": "X", "field": "y", "hide_from_roles": []},   # empty roles
            {"entity": "X", "field": "y", "hide_from_roles": "not-a-list"},
            {"entity": "X", "field": "y", "hide_from_roles": ["candidate"]},
        ],
        "entities": [{"name": "X", "fields": [{"name": "y"}]}],
    }
    result = wire_field_visibility(plan)
    y = next(f for f in result["entities"][0]["fields"] if f["name"] == "y")
    assert y["hidden_from_roles"] == ["candidate"]


# ── entity-schema annotation ───────────────────────────────────

def test_field_gets_hidden_from_roles_metadata():
    plan = {
        "field_visibility": [
            {"entity": "Feedback", "field": "notes",
             "hide_from_roles": ["candidate"]},
        ],
        "entities": [{"name": "Feedback", "fields": [
            {"name": "notes"}, {"name": "score"},
        ]}],
    }
    result = wire_field_visibility(plan)
    notes = next(f for f in result["entities"][0]["fields"]
                 if f["name"] == "notes")
    assert notes["hidden_from_roles"] == ["candidate"]
    score = next(f for f in result["entities"][0]["fields"]
                 if f["name"] == "score")
    assert "hidden_from_roles" not in score


def test_multiple_declarations_on_same_field_merge():
    plan = {
        "field_visibility": [
            {"entity": "X", "field": "y", "hide_from_roles": ["a"]},
            {"entity": "X", "field": "y", "hide_from_roles": ["b"]},
        ],
        "entities": [{"name": "X", "fields": [{"name": "y"}]}],
    }
    result = wire_field_visibility(plan)
    y = next(f for f in result["entities"][0]["fields"] if f["name"] == "y")
    assert set(y["hidden_from_roles"]) == {"a", "b"}


def test_existing_hidden_from_roles_extended_not_replaced():
    plan = {
        "field_visibility": [
            {"entity": "X", "field": "y", "hide_from_roles": ["new"]},
        ],
        "entities": [{"name": "X", "fields": [
            {"name": "y", "hidden_from_roles": ["existing"]},
        ]}],
    }
    result = wire_field_visibility(plan)
    y = result["entities"][0]["fields"][0]
    assert set(y["hidden_from_roles"]) == {"existing", "new"}


def test_untracked_field_untouched():
    plan = {
        "field_visibility": [
            {"entity": "X", "field": "y", "hide_from_roles": ["a"]},
        ],
        "entities": [{"name": "X", "fields": [
            {"name": "y"}, {"name": "z"},
        ]}],
    }
    result = wire_field_visibility(plan)
    z = next(f for f in result["entities"][0]["fields"] if f["name"] == "z")
    assert "hidden_from_roles" not in z


# ── page-field annotation ──────────────────────────────────────

def test_page_field_annotated_when_page_bound_to_tracked_entity():
    plan = {
        "field_visibility": [
            {"entity": "Feedback", "field": "notes",
             "hide_from_roles": ["candidate"]},
        ],
        "entities": [{"name": "Feedback", "fields": [{"name": "notes"}]}],
        "pages": [
            {"route": "/feedback/[id]", "entity": "Feedback",
             "fields": [{"name": "notes"}, {"name": "score"}]},
        ],
    }
    result = wire_field_visibility(plan)
    page_fields = {f["name"]: f for f in result["pages"][0]["fields"]}
    assert page_fields["notes"]["hidden_from_roles"] == ["candidate"]
    assert "hidden_from_roles" not in page_fields["score"]


# ── idempotency + immutability ─────────────────────────────────

def test_wire_is_idempotent():
    plan = {
        "field_visibility": [
            {"entity": "X", "field": "y", "hide_from_roles": ["a"]},
        ],
        "entities": [{"name": "X", "fields": [{"name": "y"}]}],
    }
    once = wire_field_visibility(plan)
    twice = wire_field_visibility(once)
    assert once == twice


def test_input_not_mutated():
    plan = {
        "field_visibility": [
            {"entity": "X", "field": "y", "hide_from_roles": ["a"]},
        ],
        "entities": [{"name": "X", "fields": [{"name": "y"}]}],
    }
    snap = copy.deepcopy(plan)
    wire_field_visibility(plan)
    assert plan == snap


# ── env gate ───────────────────────────────────────────────────

def test_env_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_FIELD_VISIBILITY", raising=False)
    assert is_field_visibility_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
def test_env_gate_truthy(monkeypatch, val):
    monkeypatch.setenv("FORGE_FIELD_VISIBILITY", val)
    assert is_field_visibility_enabled() is True
