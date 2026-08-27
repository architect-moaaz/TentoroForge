"""Tests for services.submit_authority — pure helpers for the
SUBMIT-AUTHORITY contract (Slice A of the Feature-Authoring Roadmap).

The contract:
  page.submit          = { kind, target, field_map? }
  workflow.source      = { kind, page | event | schedule }
  workflow.inputs[].source = { kind: form_field|route|auth|static|computed, ... }
"""
from __future__ import annotations

import pytest


# --------------------------------------------------------------------------- #
# resolve_page_submit
# --------------------------------------------------------------------------- #

def test_resolve_page_submit_returns_declared_target():
    from services.submit_authority import resolve_page_submit

    plan = {"pages": [{
        "name": "FeedbackFormPage",
        "type": "form",
        "submit": {"kind": "workflow", "target": "SubmitFeedbackWorkflow"},
    }]}
    r = resolve_page_submit(plan, "FeedbackFormPage")
    assert r == {
        "kind": "workflow",
        "target": "SubmitFeedbackWorkflow",
        "field_map": {},
    }


def test_resolve_page_submit_preserves_field_map():
    from services.submit_authority import resolve_page_submit

    plan = {"pages": [{
        "name": "P",
        "submit": {
            "kind": "workflow",
            "target": "W",
            "field_map": {"a": "x", "b": "y"},
        },
    }]}
    r = resolve_page_submit(plan, "P")
    assert r["field_map"] == {"a": "x", "b": "y"}


def test_resolve_page_submit_returns_none_when_undeclared():
    from services.submit_authority import resolve_page_submit

    plan = {"pages": [{"name": "P", "type": "list"}]}   # no submit
    assert resolve_page_submit(plan, "P") is None


def test_resolve_page_submit_returns_none_for_unknown_page():
    from services.submit_authority import resolve_page_submit

    plan = {"pages": [{"name": "Other", "submit": {"kind": "workflow", "target": "W"}}]}
    assert resolve_page_submit(plan, "Missing") is None


def test_resolve_page_submit_default_kind_data_api():
    from services.submit_authority import resolve_page_submit

    plan = {"pages": [{"name": "P", "submit": {"target": "Feedback"}}]}   # kind omitted
    r = resolve_page_submit(plan, "P")
    assert r["kind"] == "data_api"    # default when kind omitted


def test_resolve_page_submit_returns_none_on_malformed_plan():
    from services.submit_authority import resolve_page_submit

    assert resolve_page_submit(None, "P") is None
    assert resolve_page_submit({}, "P") is None
    assert resolve_page_submit({"pages": "not a list"}, "P") is None


# --------------------------------------------------------------------------- #
# resolve_workflow_source
# --------------------------------------------------------------------------- #

def test_resolve_workflow_source_returns_declared_source():
    from services.submit_authority import resolve_workflow_source

    plan = {"workflows": [{
        "name": "W",
        "source": {"kind": "form", "page": "FeedbackFormPage"},
    }]}
    r = resolve_workflow_source(plan, "W")
    assert r == {"kind": "form", "page": "FeedbackFormPage"}


def test_resolve_workflow_source_returns_none_when_undeclared():
    from services.submit_authority import resolve_workflow_source

    plan = {"workflows": [{"name": "W"}]}
    assert resolve_workflow_source(plan, "W") is None


def test_resolve_workflow_source_returns_none_on_malformed_plan():
    from services.submit_authority import resolve_workflow_source

    assert resolve_workflow_source(None, "W") is None
    assert resolve_workflow_source({}, "W") is None


# --------------------------------------------------------------------------- #
# derive_form_fields_from_workflow
# --------------------------------------------------------------------------- #

def test_derive_form_fields_only_form_field_sources():
    from services.submit_authority import derive_form_fields_from_workflow

    plan = {"workflows": [{
        "name": "W",
        "inputs": [
            {"name": "a", "type": "uuid",   "source": {"kind": "form_field", "field": "a"}},
            {"name": "b", "type": "integer","source": {"kind": "form_field", "field": "b"}},
            {"name": "c", "type": "uuid",   "source": {"kind": "route",      "param": "id"}},
            {"name": "d", "type": "uuid",   "source": {"kind": "auth",       "claim": "user.id"}},
        ],
    }]}
    fields = derive_form_fields_from_workflow(plan, "W")
    # Only form_field inputs appear as form fields.
    assert [f["name"] for f in fields] == ["a", "b"]
    # Type + required carried through so the scaffolder can build the control.
    assert all("type" in f for f in fields)


def test_derive_form_fields_uses_field_name_when_different():
    from services.submit_authority import derive_form_fields_from_workflow

    plan = {"workflows": [{
        "name": "W",
        "inputs": [{
            "name": "cvUrl",
            "type": "string",
            "source": {"kind": "form_field", "field": "resume"},  # form-side alias
        }],
    }]}
    fields = derive_form_fields_from_workflow(plan, "W")
    # Field NAME on the form uses source.field (what the form control's name is),
    # not the workflow input name.
    assert fields[0]["name"] == "resume"
    assert fields[0].get("workflow_input") == "cvUrl"  # trace back to workflow


def test_derive_form_fields_returns_empty_for_unknown_workflow():
    from services.submit_authority import derive_form_fields_from_workflow

    plan = {"workflows": [{"name": "Other", "inputs": []}]}
    assert derive_form_fields_from_workflow(plan, "Missing") == []


def test_derive_form_fields_returns_empty_when_no_inputs():
    from services.submit_authority import derive_form_fields_from_workflow

    plan = {"workflows": [{"name": "W"}]}
    assert derive_form_fields_from_workflow(plan, "W") == []


# --------------------------------------------------------------------------- #
# validate_input_sources
# --------------------------------------------------------------------------- #

def test_validate_input_sources_all_declared_ok():
    from services.submit_authority import validate_input_sources

    workflow = {"name": "W", "inputs": [
        {"name": "a", "required": True, "source": {"kind": "form_field", "field": "a"}},
        {"name": "b", "required": True, "source": {"kind": "route", "param": "id"}},
        {"name": "c", "required": True, "source": {"kind": "auth",  "claim": "user.id"}},
        {"name": "d", "required": False, "source": {"kind": "static", "value": "{{now}}"}},
    ]}
    page = {"name": "P", "type": "form"}
    errors = validate_input_sources(workflow, page, route="/x/[id]")
    assert errors == []


def test_validate_input_sources_missing_source_errors():
    from services.submit_authority import validate_input_sources

    workflow = {"name": "W", "inputs": [
        {"name": "a", "required": True},   # no source at all
    ]}
    errors = validate_input_sources(workflow, page={"name": "P"}, route="/x")
    assert len(errors) == 1
    assert errors[0]["kind"] == "missing_source"
    assert errors[0]["input"] == "a"


def test_validate_input_sources_route_param_not_declared_by_page():
    from services.submit_authority import validate_input_sources

    workflow = {"name": "W", "inputs": [
        {"name": "id", "required": True, "source": {"kind": "route", "param": "id"}},
    ]}
    # Route has no :id param — validator flags the mismatch.
    errors = validate_input_sources(workflow, page={"name": "P"}, route="/x")
    assert len(errors) == 1
    assert errors[0]["kind"] == "route_param_missing"


def test_validate_input_sources_unknown_kind_errors():
    from services.submit_authority import validate_input_sources

    workflow = {"name": "W", "inputs": [
        {"name": "a", "required": True, "source": {"kind": "made_up"}},
    ]}
    errors = validate_input_sources(workflow, page={"name": "P"}, route="/x")
    assert len(errors) == 1
    assert errors[0]["kind"] == "unknown_source_kind"


def test_validate_input_sources_optional_missing_source_is_ok():
    from services.submit_authority import validate_input_sources

    workflow = {"name": "W", "inputs": [
        {"name": "notes", "required": False},   # optional, no source — OK
    ]}
    errors = validate_input_sources(workflow, page={"name": "P"}, route="/x")
    assert errors == []
