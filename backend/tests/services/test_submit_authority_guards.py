"""Tests for services.submit_authority_guards.

Slice A T7 + T8. Post-gen guards for the contract invariants.
"""
from __future__ import annotations

import json
from pathlib import Path


def _scaffold(tmp_path: Path, pages: list[tuple[str, dict]],
              workflows: list[tuple[str, dict]],
              plan: dict | None = None) -> Path:
    outdir = tmp_path / "app"
    (outdir / "src" / "schemas").mkdir(parents=True)
    (outdir / "workflows").mkdir(parents=True)
    (outdir / "src" / "contracts").mkdir(parents=True)
    for rel, page in pages:
        target = outdir / "src" / "schemas" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(page))
    for name, wf in workflows:
        (outdir / "workflows" / f"{name}.json").write_text(json.dumps(wf))
    if plan is not None:
        (outdir / "src" / "contracts" / "plan.json").write_text(json.dumps(plan))
    return outdir


def _form_page(route: str, workflow: str | None = None) -> dict:
    form_props: dict = {"submitLabel": "Submit"}
    if workflow:
        form_props["workflow"] = workflow
    return {"route": route, "root": {"component": "Stack", "children": [
        {"component": "Form", "props": form_props, "children": [
            {"component": "Input", "props": {"name": "a"}},
        ]},
    ]}}


# --------------------------------------------------------------------------- #
# workflow_completeness_guard
# --------------------------------------------------------------------------- #

def test_workflow_completeness_all_wired_passes(tmp_path):
    from services.submit_authority_guards import workflow_completeness_guard

    outdir = _scaffold(
        tmp_path,
        pages=[("f/new.json", _form_page("/f/new", "MyWorkflow"))],
        workflows=[("myworkflow", {"name": "MyWorkflow"})],
    )
    r = workflow_completeness_guard(str(outdir))
    assert r["ok"] is True
    assert r["violations"] == []


def test_workflow_completeness_orphan_flagged(tmp_path):
    from services.submit_authority_guards import workflow_completeness_guard

    outdir = _scaffold(
        tmp_path,
        pages=[("f/new.json", _form_page("/f/new", "OtherWorkflow"))],
        workflows=[
            ("otherworkflow", {"name": "OtherWorkflow"}),
            ("orphan", {"name": "OrphanWorkflow"}),   # not targeted
        ],
    )
    r = workflow_completeness_guard(str(outdir))
    assert r["ok"] is False
    assert len(r["violations"]) == 1
    assert r["violations"][0]["name"] == "OrphanWorkflow"


# --------------------------------------------------------------------------- #
# form_target_guard
# --------------------------------------------------------------------------- #

def test_form_target_workflow_prop_passes(tmp_path):
    from services.submit_authority_guards import form_target_guard

    outdir = _scaffold(
        tmp_path,
        pages=[("f/new.json", _form_page("/f/new", "W"))],
        workflows=[],
    )
    r = form_target_guard(str(outdir))
    assert r["ok"] is True


def test_form_target_missing_workflow_and_no_plan_submit_fails(tmp_path):
    from services.submit_authority_guards import form_target_guard

    outdir = _scaffold(
        tmp_path,
        pages=[("f/new.json", _form_page("/f/new"))],   # no workflow prop
        workflows=[],
        plan={"pages": [{"name": "P", "type": "form", "route": "/f/new"}]},  # no submit
    )
    r = form_target_guard(str(outdir))
    assert r["ok"] is False
    assert len(r["violations"]) == 1
    assert r["violations"][0]["route"] == "/f/new"


def test_form_target_plan_declared_data_api_passes(tmp_path):
    from services.submit_authority_guards import form_target_guard

    outdir = _scaffold(
        tmp_path,
        pages=[("f/new.json", _form_page("/f/new"))],   # no workflow prop
        workflows=[],
        plan={"pages": [{
            "name": "P", "type": "form", "route": "/f/new",
            "submit": {"kind": "data_api", "target": "F"},
        }]},
    )
    r = form_target_guard(str(outdir))
    assert r["ok"] is True


def test_form_target_non_form_pages_ignored(tmp_path):
    from services.submit_authority_guards import form_target_guard

    outdir = _scaffold(
        tmp_path,
        pages=[("list.json", {
            "route": "/list", "root": {"component": "Stack", "children": [
                {"component": "Table", "props": {}},
            ]},
        })],
        workflows=[],
    )
    r = form_target_guard(str(outdir))
    assert r["ok"] is True
