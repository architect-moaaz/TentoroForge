"""wizard_wire — the fifth wire-pass primitive.

Turns a wizard declaration into a form page with per-field
``wizard_step`` metadata + a ``wizard`` block on the page. The
runtime :file:`WizardShell.tsx` reads this shape to drive the step
machinery client-side."""
from __future__ import annotations

import copy

import pytest

from services.wizard_wire import is_wizard_enabled, wire_wizards


def _basic_decl(**overrides):
    d = {
        "name":     "candidate_application",
        "route":    "/candidate/apply",
        "entity":   "Candidate",
        "workflow": "submit_candidate_application",
        "steps": [
            {"title": "Personal",   "fields": ["full_name", "email"]},
            {"title": "Documents",  "fields": ["cv"]},
        ],
    }
    d.update(overrides)
    return d


# ── no-op paths ────────────────────────────────────────────────

def test_no_declaration_is_no_op():
    plan = {"pages": [{"route": "/x"}]}
    assert wire_wizards(plan) == plan


def test_none_plan_returns_verbatim():
    assert wire_wizards(None) is None


def test_malformed_entries_dropped():
    plan = {
        "wizards": [
            "not a dict",
            {},                                                # missing everything
            {"name": "x", "route": "no-slash", "entity": "X",  # bad route
             "steps": [{"fields": ["y"]}]},
            {"name": "x", "route": "/x", "entity": "X",        # empty steps
             "steps": []},
            {"name": "x", "route": "/x", "entity": "X",        # step with no fields
             "steps": [{"title": "S", "fields": []}]},
            _basic_decl(),                                     # valid
        ],
    }
    result = wire_wizards(plan)
    routes = [p["route"] for p in result.get("pages", [])]
    assert "/candidate/apply" in routes
    assert len(routes) == 1  # only the valid one materialized


# ── emitted page shape ─────────────────────────────────────────

def test_wizard_page_has_form_archetype_and_wizard_metadata():
    plan = {"wizards": [_basic_decl()]}
    result = wire_wizards(plan)
    page = result["pages"][0]
    assert page["archetype"] == "form"
    assert page["entity"] == "Candidate"
    assert "wizard" in page
    assert len(page["wizard"]["steps"]) == 2


def test_wizard_steps_carry_titles_and_field_names():
    plan = {"wizards": [_basic_decl()]}
    result = wire_wizards(plan)
    steps = result["pages"][0]["wizard"]["steps"]
    assert steps[0]["title"] == "Personal"
    assert steps[0]["field_names"] == ["full_name", "email"]
    assert steps[1]["title"] == "Documents"
    assert steps[1]["field_names"] == ["cv"]


def test_fields_tagged_with_wizard_step_index():
    plan = {"wizards": [_basic_decl()]}
    result = wire_wizards(plan)
    fields = {f["name"]: f for f in result["pages"][0]["fields"]}
    assert fields["full_name"]["wizard_step"] == 0
    assert fields["email"]["wizard_step"] == 0
    assert fields["cv"]["wizard_step"] == 1


def test_form_submit_action_wired_from_declaration():
    plan = {"wizards": [_basic_decl(workflow="foo")]}
    result = wire_wizards(plan)
    actions = result["pages"][0]["actions"]
    assert len(actions) == 1
    assert actions[0]["kind"] == "form_submit"
    assert actions[0]["workflow"] == "foo"


def test_missing_workflow_leaves_actions_empty_for_downstream_inference():
    plan = {"wizards": [_basic_decl(workflow=None)]}
    result = wire_wizards(plan)
    assert result["pages"][0]["actions"] == []


def test_step_title_defaults_when_absent():
    plan = {"wizards": [_basic_decl(steps=[
        {"fields": ["a"]},
        {"fields": ["b"]},
    ])]}
    result = wire_wizards(plan)
    steps = result["pages"][0]["wizard"]["steps"]
    assert steps[0]["title"] == "Step 1"
    assert steps[1]["title"] == "Step 2"


def test_wizard_page_name_from_declaration():
    plan = {"wizards": [_basic_decl(name="my_wizard")]}
    result = wire_wizards(plan)
    assert result["pages"][0]["name"] == "my_wizard"


# ── existing-page handling ─────────────────────────────────────

def test_wizard_route_collision_leaves_existing_page_untouched():
    """Idempotency + never overwrite an author's page. If a page
    already sits at the declared route, we skip that wizard."""
    plan = {
        "wizards": [_basic_decl(route="/candidate/apply")],
        "pages":   [{"route": "/candidate/apply", "authored": True}],
    }
    result = wire_wizards(plan)
    pages_at_route = [p for p in result["pages"]
                      if p["route"] == "/candidate/apply"]
    assert len(pages_at_route) == 1
    assert pages_at_route[0].get("authored") is True


def test_pages_key_created_when_missing():
    plan = {"wizards": [_basic_decl()]}
    result = wire_wizards(plan)
    assert isinstance(result.get("pages"), list)
    assert len(result["pages"]) == 1


# ── idempotency + immutability ─────────────────────────────────

def test_wire_is_idempotent():
    plan = {"wizards": [_basic_decl()]}
    once = wire_wizards(plan)
    twice = wire_wizards(once)
    assert once == twice


def test_input_not_mutated():
    plan = {"wizards": [_basic_decl()], "pages": []}
    snap = copy.deepcopy(plan)
    wire_wizards(plan)
    assert plan == snap


# ── env gate ───────────────────────────────────────────────────

def test_env_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_WIZARD", raising=False)
    assert is_wizard_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
def test_env_gate_truthy(monkeypatch, val):
    monkeypatch.setenv("FORGE_WIZARD", val)
    assert is_wizard_enabled() is True
