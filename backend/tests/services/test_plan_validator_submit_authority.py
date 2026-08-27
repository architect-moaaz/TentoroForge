"""Tests for the three SUBMIT-AUTHORITY rules in plan_validator.

Slice A T3. Each rule surfaces one class of orphan / mis-wiring at
plan time so downstream generation never sees it.
"""
from __future__ import annotations


# --------------------------------------------------------------------------- #
# Rule: forms_have_submit
# --------------------------------------------------------------------------- #

def test_form_page_without_submit_flagged():
    from services.plan_validator import validate_plan

    plan = {
        "data_models": [{"name": "F", "fields": []}],
        "pages": [{"name": "P", "type": "form", "entity": "F"}],  # no submit
    }
    vs = validate_plan(plan)
    subs = [v for v in vs if v["rule"] == "form_missing_submit"]
    assert len(subs) == 1
    assert "P" in subs[0]["message"]


def test_form_page_with_submit_passes():
    from services.plan_validator import validate_plan

    plan = {
        "data_models": [{"name": "F", "fields": []}],
        "pages": [{
            "name": "P", "type": "form", "entity": "F",
            "submit": {"kind": "data_api", "target": "F"},
        }],
    }
    vs = validate_plan(plan)
    assert not any(v["rule"] == "form_missing_submit" for v in vs)


def test_form_submit_target_missing_flagged():
    from services.plan_validator import validate_plan

    plan = {
        "data_models": [{"name": "F", "fields": []}],
        "pages": [{
            "name": "P", "type": "form", "entity": "F",
            "submit": {"kind": "workflow", "target": "DoesNotExist"},
        }],
        "workflows": [],
    }
    vs = validate_plan(plan)
    ts = [v for v in vs if v["rule"] == "submit_target_missing"]
    assert len(ts) == 1
    assert "DoesNotExist" in ts[0]["message"]


# --------------------------------------------------------------------------- #
# Rule: workflows_have_source
# --------------------------------------------------------------------------- #

def test_workflow_without_source_flagged():
    from services.plan_validator import validate_plan

    plan = {
        "data_models": [{"name": "F", "fields": []}],
        "workflows": [{"name": "SomeWorkflow", "inputs": []}],  # no source
    }
    vs = validate_plan(plan)
    subs = [v for v in vs if v["rule"] == "workflow_missing_source"]
    assert len(subs) == 1
    assert "SomeWorkflow" in subs[0]["message"]


def test_workflow_with_source_passes():
    from services.plan_validator import validate_plan

    plan = {
        "data_models": [{"name": "F", "fields": []}],
        "pages": [{
            "name": "P", "type": "form", "entity": "F", "route": "/f/new",
            "submit": {"kind": "workflow", "target": "W"},
        }],
        "workflows": [{
            "name": "W",
            "source": {"kind": "form", "page": "P"},
            "inputs": [],
        }],
    }
    vs = validate_plan(plan)
    assert not any(v["rule"] == "workflow_missing_source" for v in vs)


def test_workflow_source_page_missing_flagged():
    from services.plan_validator import validate_plan

    plan = {
        "workflows": [{
            "name": "W",
            "source": {"kind": "form", "page": "NoSuchPage"},
            "inputs": [],
        }],
    }
    vs = validate_plan(plan)
    subs = [v for v in vs if v["rule"] == "workflow_source_page_missing"]
    assert len(subs) == 1
    assert "NoSuchPage" in subs[0]["message"]


# --------------------------------------------------------------------------- #
# Rule: input_sources_resolve
# --------------------------------------------------------------------------- #

def test_input_source_form_field_missing_flagged():
    from services.plan_validator import validate_plan

    plan = {
        "data_models": [{"name": "F", "fields": []}],
        "pages": [{
            "name": "P", "type": "form", "entity": "F", "route": "/f/new",
            "submit": {"kind": "workflow", "target": "W"},
            "fields": [{"name": "existing"}],   # form has only `existing`
        }],
        "workflows": [{
            "name": "W",
            "source": {"kind": "form", "page": "P"},
            "inputs": [{
                "name": "missing", "type": "string", "required": True,
                "source": {"kind": "form_field", "field": "missing"},
            }],
        }],
    }
    vs = validate_plan(plan)
    subs = [v for v in vs if v["rule"] == "input_source_form_field_missing"]
    assert len(subs) == 1


def test_input_source_route_param_missing_flagged():
    from services.plan_validator import validate_plan

    plan = {
        "data_models": [{"name": "F", "fields": []}],
        "pages": [{
            "name": "P", "type": "form", "entity": "F", "route": "/f/new",
            "submit": {"kind": "workflow", "target": "W"},
            "fields": [],
        }],
        "workflows": [{
            "name": "W",
            "source": {"kind": "form", "page": "P"},
            "inputs": [{
                "name": "id", "type": "uuid", "required": True,
                "source": {"kind": "route", "param": "id"},  # /f/new has no :id
            }],
        }],
    }
    vs = validate_plan(plan)
    subs = [v for v in vs if v["rule"] == "input_source_route_param_missing"]
    assert len(subs) == 1


def test_input_missing_source_flagged():
    from services.plan_validator import validate_plan

    plan = {
        "data_models": [{"name": "F", "fields": []}],
        "workflows": [{
            "name": "W",
            "source": {"kind": "form", "page": "P"},
            "inputs": [{"name": "x", "type": "string", "required": True}],  # no source
        }],
        "pages": [{
            "name": "P", "type": "form", "entity": "F", "route": "/x",
            "submit": {"kind": "workflow", "target": "W"},
        }],
    }
    vs = validate_plan(plan)
    subs = [v for v in vs if v["rule"] == "input_missing_source"]
    assert len(subs) == 1
