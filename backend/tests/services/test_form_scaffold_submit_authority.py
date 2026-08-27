"""Tests for services.form_scaffold.scaffold_forms_from_workflow_inputs.

Slice A T4. When a page dispatches a workflow (Form.props.workflow set +
plan.pages[].submit.kind=workflow), the form's field list is derived
from the workflow's ``inputs[].source=form_field`` declarations —
independent of the entity's columns. This pass adds any missing fields
so submit dispatches with complete data.
"""
from __future__ import annotations

import json
from pathlib import Path


def _scaffold(tmp_path: Path, page: dict, plan: dict) -> Path:
    outdir = tmp_path / "app"
    (outdir / "src" / "schemas").mkdir(parents=True)
    (outdir / "src" / "contracts").mkdir(parents=True)
    schema_path = outdir / "src" / "schemas" / f"{page['route'].strip('/').replace('/', '__')}.json"
    schema_path.write_text(json.dumps(page, indent=2))
    (outdir / "src" / "contracts" / "plan.json").write_text(json.dumps(plan))
    return outdir


def _minimal_form_page(route: str, workflow_name: str, existing_fields: list[str]) -> dict:
    return {
        "route": route,
        "root": {
            "component": "Stack", "children": [{
                "component": "Form",
                "props": {"workflow": workflow_name, "submitLabel": "Submit"},
                "children": [
                    {"component": "Input", "props": {"name": n}} for n in existing_fields
                ],
            }],
        },
    }


# --------------------------------------------------------------------------- #
# Test 1 — missing workflow form_field input gets added to the form
# --------------------------------------------------------------------------- #

def test_missing_workflow_field_is_added(tmp_path):
    from services.form_scaffold import scaffold_forms_from_workflow_inputs

    page = _minimal_form_page("/feedback/new", "SubmitFeedback",
                              existing_fields=["rating"])
    plan = {
        "pages": [{
            "name": "FB", "type": "form", "route": "/feedback/new",
            "submit": {"kind": "workflow", "target": "SubmitFeedback"},
        }],
        "workflows": [{
            "name": "SubmitFeedback",
            "source": {"kind": "form", "page": "FB"},
            "inputs": [
                {"name": "rating", "type": "integer", "required": True,
                 "source": {"kind": "form_field", "field": "rating"}},
                {"name": "notes",  "type": "text",    "required": False,
                 "source": {"kind": "form_field", "field": "notes"}},
            ],
        }],
    }
    outdir = _scaffold(tmp_path, page, plan)

    result = scaffold_forms_from_workflow_inputs(str(outdir))
    assert result["added"] == 1     # `notes` was missing
    schema_path = outdir / "src" / "schemas" / "feedback__new.json"
    doc = json.loads(schema_path.read_text())
    field_names = {c["props"]["name"]
                   for c in doc["root"]["children"][0]["children"]
                   if isinstance(c, dict) and "props" in c}
    assert "notes" in field_names


# --------------------------------------------------------------------------- #
# Test 2 — form already covering all workflow fields → no changes
# --------------------------------------------------------------------------- #

def test_complete_form_leaves_schema_alone(tmp_path):
    from services.form_scaffold import scaffold_forms_from_workflow_inputs

    page = _minimal_form_page("/f/new", "W", existing_fields=["a", "b"])
    plan = {
        "pages": [{"name": "P", "type": "form", "route": "/f/new",
                   "submit": {"kind": "workflow", "target": "W"}}],
        "workflows": [{
            "name": "W",
            "source": {"kind": "form", "page": "P"},
            "inputs": [
                {"name": "a", "source": {"kind": "form_field", "field": "a"}, "required": True},
                {"name": "b", "source": {"kind": "form_field", "field": "b"}, "required": True},
            ],
        }],
    }
    outdir = _scaffold(tmp_path, page, plan)
    before = (outdir / "src" / "schemas" / "f__new.json").read_text()

    result = scaffold_forms_from_workflow_inputs(str(outdir))
    assert result["added"] == 0
    assert (outdir / "src" / "schemas" / "f__new.json").read_text() == before


# --------------------------------------------------------------------------- #
# Test 3 — non-form_field inputs (route/auth/static) are NOT scaffolded
# --------------------------------------------------------------------------- #

def test_route_and_auth_inputs_not_scaffolded(tmp_path):
    from services.form_scaffold import scaffold_forms_from_workflow_inputs

    page = _minimal_form_page("/f/[id]/edit", "W", existing_fields=[])
    plan = {
        "pages": [{"name": "P", "type": "form", "route": "/f/[id]/edit",
                   "submit": {"kind": "workflow", "target": "W"}}],
        "workflows": [{
            "name": "W",
            "source": {"kind": "form", "page": "P"},
            "inputs": [
                {"name": "id",         "source": {"kind": "route", "param": "id"}, "required": True},
                {"name": "recordedBy", "source": {"kind": "auth",  "claim": "user.id"}, "required": True},
                {"name": "when",       "source": {"kind": "static","value": "{{now}}"},  "required": True},
            ],
        }],
    }
    outdir = _scaffold(tmp_path, page, plan)
    result = scaffold_forms_from_workflow_inputs(str(outdir))
    # No form_field inputs → nothing to add.
    assert result["added"] == 0


# --------------------------------------------------------------------------- #
# Test 4 — data_api submit forms are skipped by this pass (entity path
#          handles them via scaffold_forms)
# --------------------------------------------------------------------------- #

def test_data_api_submit_skipped(tmp_path):
    from services.form_scaffold import scaffold_forms_from_workflow_inputs

    page = _minimal_form_page("/candidates/new", "CreateCandidate",
                              existing_fields=["name"])
    plan = {
        "pages": [{"name": "P", "type": "form", "route": "/candidates/new",
                   "submit": {"kind": "data_api", "target": "Candidate"}}],
        "workflows": [],
    }
    outdir = _scaffold(tmp_path, page, plan)
    result = scaffold_forms_from_workflow_inputs(str(outdir))
    assert result["added"] == 0
