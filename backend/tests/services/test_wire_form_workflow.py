"""Tests for services.wire_form_workflow._resolve_wiring — the pure
resolver that decides how a form dispatches a workflow given both
artifacts + an optional field map.

Slice C (Feature-Authoring Roadmap 2026-07-20) Task 1."""
from __future__ import annotations

import pytest


# --------------------------------------------------------------------------- #
# Fixture helpers — build canonical page + workflow shapes
# --------------------------------------------------------------------------- #

def _page(route: str, form_children: list[dict], form_props: dict | None = None) -> dict:
    return {
        "route": route,
        "root": {
            "component": "Stack",
            "children": [{
                "component": "Form",
                "props": form_props or {},
                "children": form_children,
            }],
        },
    }


def _input(name: str, kind: str = "Input") -> dict:
    return {"component": kind, "props": {"name": name}}


def _workflow(name: str, process_vars: list[dict], trigger: dict | None = None) -> dict:
    return {
        "id": name.lower(),
        "name": name,
        "processVariables": process_vars,
        "definition": {"trigger": trigger or {"type": "manual"}, "nodes": []},
    }


# --------------------------------------------------------------------------- #
# Test 1 — Identity map when form and workflow field names match 1:1
# --------------------------------------------------------------------------- #

def test_resolve_wiring_identity_map():
    from services.wire_form_workflow import _resolve_wiring

    page = _page("/candidates/new", [_input("cvUrl"), _input("fullName")])
    wf = _workflow("ParseCvWorkflow", [
        {"name": "cvUrl",    "type": "string", "required": True},
        {"name": "fullName", "type": "string", "required": True},
    ])
    r = _resolve_wiring(page, wf)

    assert r["error"] is None
    assert r["field_map"] == {"cvUrl": "cvUrl", "fullName": "fullName"}
    assert r["input_sources"] == {
        "cvUrl":    {"kind": "form_field", "field": "cvUrl"},
        "fullName": {"kind": "form_field", "field": "fullName"},
    }
    assert r["form_props_patch"] == {"workflow": "ParseCvWorkflow"}
    assert r["workflow_source_patch"] == {
        "kind": "form",
        "page": "/candidates/new",
    }


# --------------------------------------------------------------------------- #
# Test 2 — Explicit field_map overrides identity derivation
# --------------------------------------------------------------------------- #

def test_resolve_wiring_explicit_field_map():
    from services.wire_form_workflow import _resolve_wiring

    page = _page("/candidates/new", [_input("resume"), _input("name")])
    wf = _workflow("ParseCvWorkflow", [
        {"name": "cvUrl",    "type": "string", "required": True},
        {"name": "fullName", "type": "string", "required": True},
    ])
    r = _resolve_wiring(page, wf, field_map={"resume": "cvUrl", "name": "fullName"})

    assert r["error"] is None
    assert r["field_map"] == {"resume": "cvUrl", "name": "fullName"}
    assert r["input_sources"]["cvUrl"] == {"kind": "form_field", "field": "resume"}
    assert r["input_sources"]["fullName"] == {"kind": "form_field", "field": "name"}


# --------------------------------------------------------------------------- #
# Test 3 — Required workflow input NOT covered by any form field → error
# --------------------------------------------------------------------------- #

def test_resolve_wiring_unresolved_required_input():
    from services.wire_form_workflow import _resolve_wiring

    page = _page("/candidates/new", [_input("cvUrl")])
    wf = _workflow("ParseCvWorkflow", [
        {"name": "cvUrl",         "type": "string", "required": True},
        {"name": "candidateId",   "type": "string", "required": True},  # nothing sources this
    ])
    r = _resolve_wiring(page, wf)

    assert r["error"] is not None
    assert "candidateId" in r["error"]
    assert r["error"].startswith("unresolved_input:")
    # cvUrl still got resolved — error reports the specific gap
    assert r["input_sources"].get("cvUrl") == {"kind": "form_field", "field": "cvUrl"}


# --------------------------------------------------------------------------- #
# Test 4 — Route param auto-resolves when page.route declares it
# --------------------------------------------------------------------------- #

def test_resolve_wiring_route_param_auto_resolves():
    from services.wire_form_workflow import _resolve_wiring

    # Route has :id — page can source workflow inputs named "id" from the URL
    page = _page("/candidates/[id]/feedback", [_input("rating")])
    wf = _workflow("SubmitFeedbackWorkflow", [
        {"name": "rating", "type": "integer", "required": True},
        {"name": "id",     "type": "string",  "required": True},   # from route
    ])
    r = _resolve_wiring(page, wf)

    assert r["error"] is None
    assert r["input_sources"]["rating"] == {"kind": "form_field", "field": "rating"}
    assert r["input_sources"]["id"] == {"kind": "route", "param": "id"}


# --------------------------------------------------------------------------- #
# Test 5 — Non-required input NOT covered → OK (no error), input omitted
#          from input_sources so the runtime dispatcher sees "no value"
# --------------------------------------------------------------------------- #

def test_resolve_wiring_optional_input_missing_is_fine():
    from services.wire_form_workflow import _resolve_wiring

    page = _page("/x/new", [_input("a")])
    wf = _workflow("W", [
        {"name": "a", "type": "string", "required": True},
        {"name": "b", "type": "string", "required": False},   # optional, missing
    ])
    r = _resolve_wiring(page, wf)

    assert r["error"] is None
    assert "b" not in r["input_sources"]      # no source — dispatcher will
                                              # pass no value; workflow tolerates


# --------------------------------------------------------------------------- #
# Test 6 — Page with no Form component → trigger_not_found
# --------------------------------------------------------------------------- #

def test_resolve_wiring_no_form_on_page():
    from services.wire_form_workflow import _resolve_wiring

    page = {"route": "/candidates", "root": {
        "component": "Stack",
        "children": [{"component": "Table", "props": {}}],
    }}
    wf = _workflow("X", [])
    r = _resolve_wiring(page, wf)

    assert r["error"] is not None
    assert r["error"].startswith("trigger_not_found:")


# --------------------------------------------------------------------------- #
# Task 2 — File I/O + atomic write
# --------------------------------------------------------------------------- #

import json
from pathlib import Path


def _scaffold_project(tmp_path: Path, page: dict, wf: dict) -> Path:
    """Build a minimal output_dir on disk with one page + one workflow."""
    outdir = tmp_path / "app"
    (outdir / "src" / "schemas" / "candidates").mkdir(parents=True, exist_ok=True)
    (outdir / "workflows").mkdir(parents=True, exist_ok=True)
    (outdir / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    # Page at src/schemas/candidates/new.json
    (outdir / "src" / "schemas" / "candidates" / "new.json").write_text(
        json.dumps(page, indent=2), encoding="utf-8",
    )
    # Workflow at workflows/<name>.json — use lowercase to mirror real gen
    wf_id = str(wf.get("name", "wf")).lower()
    (outdir / "workflows" / f"{wf_id}.json").write_text(
        json.dumps(wf, indent=2), encoding="utf-8",
    )
    return outdir


def test_wire_writes_form_props_and_workflow_trigger(tmp_path):
    from services.wire_form_workflow import wire_form_to_workflow

    page = _page("/candidates/new", [_input("cvUrl"), _input("fullName")])
    wf = _workflow("ParseCvWorkflow", [
        {"name": "cvUrl",    "type": "string", "required": True},
        {"name": "fullName", "type": "string", "required": True},
    ])
    outdir = _scaffold_project(tmp_path, page, wf)

    r = wire_form_to_workflow(
        str(outdir),
        page_route="/candidates/new",
        workflow_name="ParseCvWorkflow",
        git=False,
    )

    assert r["applied"] is True, r
    assert r["error"] is None
    # Page: Form.props.workflow was set
    updated_page = json.loads(
        (outdir / "src" / "schemas" / "candidates" / "new.json").read_text(encoding="utf-8"),
    )
    form_props = updated_page["root"]["children"][0]["props"]
    assert form_props["workflow"] == "ParseCvWorkflow"
    # Workflow: trigger.type flipped from manual to "form", source recorded
    updated_wf = json.loads(
        (outdir / "workflows" / "parsecvworkflow.json").read_text(encoding="utf-8"),
    )
    assert updated_wf["definition"]["trigger"]["type"] == "form"
    assert updated_wf["source"] == {"kind": "form", "page": "/candidates/new"}


def test_wire_page_not_found_returns_error(tmp_path):
    from services.wire_form_workflow import wire_form_to_workflow

    page = _page("/candidates/new", [_input("a")])
    wf = _workflow("W", [])
    outdir = _scaffold_project(tmp_path, page, wf)

    r = wire_form_to_workflow(
        str(outdir),
        page_route="/does/not/exist",
        workflow_name="W",
        git=False,
    )
    assert r["applied"] is False
    assert r["error"].startswith("page_not_found:")


def test_wire_workflow_not_found_returns_error(tmp_path):
    from services.wire_form_workflow import wire_form_to_workflow

    page = _page("/candidates/new", [_input("a")])
    wf = _workflow("W", [])
    outdir = _scaffold_project(tmp_path, page, wf)

    r = wire_form_to_workflow(
        str(outdir),
        page_route="/candidates/new",
        workflow_name="NoSuchWorkflow",
        git=False,
    )
    assert r["applied"] is False
    assert r["error"].startswith("workflow_not_found:")


def test_wire_unresolved_input_returns_error_no_writes(tmp_path):
    from services.wire_form_workflow import wire_form_to_workflow

    page = _page("/candidates/new", [_input("cvUrl")])
    wf = _workflow("W", [
        {"name": "cvUrl",       "type": "string", "required": True},
        {"name": "candidateId", "type": "string", "required": True},  # unresolved
    ])
    outdir = _scaffold_project(tmp_path, page, wf)
    before_page = (outdir / "src" / "schemas" / "candidates" / "new.json").read_text(encoding="utf-8")
    before_wf   = (outdir / "workflows" / "w.json").read_text(encoding="utf-8")

    r = wire_form_to_workflow(
        str(outdir),
        page_route="/candidates/new",
        workflow_name="W",
        git=False,
    )
    assert r["applied"] is False
    assert "candidateId" in r["error"]
    # Verify no writes occurred
    assert (outdir / "src" / "schemas" / "candidates" / "new.json").read_text(encoding="utf-8") == before_page
    assert (outdir / "workflows" / "w.json").read_text(encoding="utf-8") == before_wf


# --------------------------------------------------------------------------- #
# Task 3 — Mirror wiring back to plan.json (keep plan authoritative)
# --------------------------------------------------------------------------- #

def _write_plan(outdir: Path, plan: dict) -> None:
    (outdir / "src" / "contracts" / "plan.json").write_text(
        json.dumps(plan, indent=2), encoding="utf-8",
    )


def test_wire_mirrors_page_submit_to_plan(tmp_path):
    from services.wire_form_workflow import wire_form_to_workflow

    page = _page("/candidates/new", [_input("cvUrl"), _input("fullName")])
    wf = _workflow("ParseCvWorkflow", [
        {"name": "cvUrl",    "type": "string", "required": True},
        {"name": "fullName", "type": "string", "required": True},
    ])
    outdir = _scaffold_project(tmp_path, page, wf)
    _write_plan(outdir, {
        "pages": [
            {"name": "CandidateForm", "route": "/candidates/new", "type": "form"},
        ],
        "workflows": [{"name": "ParseCvWorkflow", "trigger": "manual"}],
    })

    r = wire_form_to_workflow(
        str(outdir),
        page_route="/candidates/new",
        workflow_name="ParseCvWorkflow",
        git=False,
    )
    assert r["applied"] is True

    plan = json.loads((outdir / "src" / "contracts" / "plan.json").read_text(encoding="utf-8"))
    # page.submit populated
    page_entry = next(p for p in plan["pages"] if p["route"] == "/candidates/new")
    assert page_entry["submit"] == {
        "kind": "workflow",
        "target": "ParseCvWorkflow",
        "field_map": {"cvUrl": "cvUrl", "fullName": "fullName"},
    }
    # workflow.source populated
    wf_entry = next(w for w in plan["workflows"] if w["name"] == "ParseCvWorkflow")
    assert wf_entry["source"] == {"kind": "form", "page": "/candidates/new"}
    # workflow.inputs[].source populated
    wf_inputs = {i["name"]: i for i in wf_entry.get("inputs", [])}
    assert wf_inputs["cvUrl"]["source"] == {"kind": "form_field", "field": "cvUrl"}
    assert wf_inputs["fullName"]["source"] == {"kind": "form_field", "field": "fullName"}


def test_wire_soft_fails_when_plan_json_missing(tmp_path):
    from services.wire_form_workflow import wire_form_to_workflow

    page = _page("/candidates/new", [_input("cvUrl")])
    wf = _workflow("W", [{"name": "cvUrl", "type": "string", "required": True}])
    outdir = _scaffold_project(tmp_path, page, wf)
    # NOTE: no plan.json written

    r = wire_form_to_workflow(
        str(outdir),
        page_route="/candidates/new",
        workflow_name="W",
        git=False,
    )
    # Primary writes still succeed; only the mirror is skipped.
    assert r["applied"] is True
    assert r["error"] is None
    # Warning is surfaced in the result so callers can log it.
    warnings = [c for c in r["changes"] if c.get("kind") == "plan_mirror_warning"]
    assert len(warnings) == 1
    assert "plan.json" in warnings[0]["patch"]["reason"]
