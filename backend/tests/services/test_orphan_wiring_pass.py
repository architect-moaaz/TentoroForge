"""Tests for services.orphan_wiring_pass.

Post-gen pass that auto-wires orphan workflows (no Form.props.workflow
targets them) to their natural launcher forms by scoring input-name
overlap. Runs late in ``apply_post_generate_fixes``.
"""
from __future__ import annotations

import json
from pathlib import Path


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #

def _page(route: str, form_children: list[dict],
          form_workflow: str | None = None) -> dict:
    form_props = {"submitLabel": "Submit"}
    if form_workflow is not None:
        form_props["workflow"] = form_workflow
    return {
        "route": route,
        "root": {"component": "Stack", "children": [
            {"component": "Form", "props": form_props, "children": form_children},
        ]},
    }


def _input(name: str) -> dict:
    return {"component": "Input", "props": {"name": name}}


def _workflow(name: str, inputs: list[dict],
              *, trigger: dict | None = None) -> dict:
    return {
        "id": name.lower(),
        "name": name,
        "processVariables": inputs,
        "definition": {
            "trigger": trigger if trigger is not None else {"type": "manual"},
            "nodes": [],
        },
    }


def _scaffold(tmp_path: Path,
              pages: list[tuple[str, dict]],
              workflows: list[dict]) -> Path:
    outdir = tmp_path / "app"
    (outdir / "src" / "schemas").mkdir(parents=True, exist_ok=True)
    (outdir / "workflows").mkdir(parents=True, exist_ok=True)
    (outdir / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    for rel_path, page in pages:
        target = outdir / "src" / "schemas" / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(page, indent=2), encoding="utf-8")
    for wf in workflows:
        (outdir / "workflows" / f"{str(wf['name']).lower()}.json").write_text(
            json.dumps(wf, indent=2), encoding="utf-8",
        )
    return outdir


# --------------------------------------------------------------------------- #
# Test 1 — find orphans (workflows no page's Form.props.workflow targets)
# --------------------------------------------------------------------------- #

def test_find_orphans_returns_unwired_workflows(tmp_path):
    from services.orphan_wiring_pass import _find_orphan_workflows

    pages = [
        ("candidates/new.json",
         _page("/candidates/new", [_input("name")], form_workflow="CreateCandidateProfile")),
        ("feedback/new.json",
         _page("/feedback/new", [_input("rating")])),   # unwired
    ]
    workflows = [
        _workflow("CreateCandidateProfile", []),       # wired
        _workflow("SubmitFeedbackWorkflow", []),       # orphan
        _workflow("ParseCvWorkflow", []),              # orphan
    ]
    outdir = _scaffold(tmp_path, pages, workflows)

    orphans = _find_orphan_workflows(str(outdir))
    assert set(o["name"] for o in orphans) == {"SubmitFeedbackWorkflow", "ParseCvWorkflow"}


# --------------------------------------------------------------------------- #
# Test 2 — index unwired forms with their field signatures
# --------------------------------------------------------------------------- #

def test_index_unwired_forms(tmp_path):
    from services.orphan_wiring_pass import _index_unwired_forms

    pages = [
        ("wired.json", _page("/wired", [_input("a")], form_workflow="X")),
        ("bare.json", _page("/bare", [_input("a"), _input("b")])),
        ("listing.json", {"route": "/listing",
                          "root": {"component": "Table", "props": {}}}),  # no form
    ]
    outdir = _scaffold(tmp_path, pages, [])

    forms = _index_unwired_forms(str(outdir))
    assert len(forms) == 1
    assert forms[0]["route"] == "/bare"
    assert forms[0]["fields"] == {"a", "b"}


# --------------------------------------------------------------------------- #
# Test 3 — score a form for a workflow (fraction of required inputs covered)
# --------------------------------------------------------------------------- #

def test_score_form_for_workflow_full_coverage(tmp_path):
    from services.orphan_wiring_pass import _score_form_for_workflow

    form = {"route": "/feedback/new", "fields": {"rating", "notes"}}
    wf = _workflow("SubmitFeedbackWorkflow", [
        {"name": "rating", "type": "integer", "required": True},
        {"name": "notes",  "type": "text",    "required": False},
    ])
    score = _score_form_for_workflow(form, wf)
    # 1 required input, form covers it → full coverage = 1.0
    assert score == 1.0


def test_score_form_for_workflow_partial_no_score(tmp_path):
    from services.orphan_wiring_pass import _score_form_for_workflow

    form = {"route": "/other/new", "fields": {"a"}}
    wf = _workflow("W", [
        {"name": "a", "type": "string", "required": True},
        {"name": "b", "type": "string", "required": True},   # not in form
    ])
    # Only 1 of 2 required covered → 0.5 (below default HIGH_CONFIDENCE)
    score = _score_form_for_workflow(form, wf)
    assert 0.0 < score < 1.0


# --------------------------------------------------------------------------- #
# Test 4 — end-to-end: wire_orphan_workflows fires the seam on strong matches
# --------------------------------------------------------------------------- #

def test_wire_orphan_workflows_wires_perfect_match(tmp_path):
    from services.orphan_wiring_pass import wire_orphan_workflows

    pages = [
        ("feedback/new.json",
         _page("/feedback/new", [_input("rating")])),
    ]
    workflows = [
        _workflow("SubmitFeedbackWorkflow", [
            {"name": "rating", "type": "integer", "required": True},
        ]),
    ]
    outdir = _scaffold(tmp_path, pages, workflows)

    result = wire_orphan_workflows(str(outdir))

    assert len(result["wired"]) == 1
    assert result["wired"][0]["workflow"] == "SubmitFeedbackWorkflow"
    assert result["wired"][0]["page_route"] == "/feedback/new"
    assert result["unresolved"] == []

    # Verify the form now points at the workflow.
    page = json.loads(
        (outdir / "src" / "schemas" / "feedback" / "new.json").read_text(encoding="utf-8"),
    )
    form = page["root"]["children"][0]
    assert form["props"]["workflow"] == "SubmitFeedbackWorkflow"


# --------------------------------------------------------------------------- #
# Test 5 — orphan with no candidate form is surfaced as unresolved
# --------------------------------------------------------------------------- #

def test_wire_orphan_workflows_unresolved_when_no_match(tmp_path):
    from services.orphan_wiring_pass import wire_orphan_workflows

    pages = [
        ("candidates/new.json",
         _page("/candidates/new", [_input("name")], form_workflow="Create")),
    ]
    workflows = [
        _workflow("SomeOtherWorkflow", [
            {"name": "unrelatedField", "type": "string", "required": True},
        ]),
    ]
    outdir = _scaffold(tmp_path, pages, workflows)

    result = wire_orphan_workflows(str(outdir))
    assert result["wired"] == []
    assert len(result["unresolved"]) == 1
    assert result["unresolved"][0]["workflow"] == "SomeOtherWorkflow"
    assert result["unresolved"][0]["reason"] == "no_matching_form"


# --------------------------------------------------------------------------- #
# Test 6 — never overwrites an existing wire (safety)
# --------------------------------------------------------------------------- #

def test_wire_orphan_workflows_never_overwrites_wired_form(tmp_path):
    from services.orphan_wiring_pass import wire_orphan_workflows

    # Only one form, ALREADY wired to CreateCandidateProfile.
    # A domain orphan (ParseCvWorkflow) also matches its fields.
    pages = [
        ("candidates/new.json",
         _page("/candidates/new",
               [_input("cvUrl")],
               form_workflow="CreateCandidateProfile")),
    ]
    workflows = [
        _workflow("CreateCandidateProfile", [
            {"name": "cvUrl", "type": "string", "required": True},
        ]),
        _workflow("ParseCvWorkflow", [
            {"name": "cvUrl", "type": "string", "required": True},
        ]),
    ]
    outdir = _scaffold(tmp_path, pages, workflows)

    result = wire_orphan_workflows(str(outdir))
    # ParseCvWorkflow stays unresolved — form is already claimed.
    assert result["wired"] == []
    assert any(u["workflow"] == "ParseCvWorkflow" for u in result["unresolved"])
    # The original wire is intact.
    page = json.loads(
        (outdir / "src" / "schemas" / "candidates" / "new.json").read_text(encoding="utf-8"),
    )
    assert page["root"]["children"][0]["props"]["workflow"] == "CreateCandidateProfile"


# --------------------------------------------------------------------------- #
# Test 7 (VPS-M) — api_event workflows ARE wired to a matching form
# --------------------------------------------------------------------------- #

def test_wire_orphan_workflows_wires_api_event_trigger(tmp_path):
    """Regression for VPS-M — the /scan symptom.

    A workflow whose trigger.type is ``api_event`` (e.g.
    ``ScanProductWorkflow`` with ``event: scan_submitted``) must be
    picked up as an orphan and wired to the /scan Form whose FileUpload
    is named ``imageUrl``. Before VPS-M the pass had an implicit
    manual-only gate downstream that left this class of workflow
    forever unwired, so the /scan Form dispatched nothing and the
    page stuck at "Status: pending — auto-refreshes forever".
    """
    from services.orphan_wiring_pass import wire_orphan_workflows

    pages = [
        # Mirrors what archetype_page_fixes.py emits before the Form gets
        # wired (Form has no props.workflow yet — the fixture omits it to
        # simulate an emitter that ran without setting the workflow prop).
        ("scan.json", _page("/scan", [_input("imageUrl")])),
    ]
    workflows = [
        _workflow(
            "ScanProductWorkflow",
            [{"name": "imageUrl", "type": "string", "required": True}],
            trigger={"type": "api_event", "event": "scan_submitted"},
        ),
    ]
    outdir = _scaffold(tmp_path, pages, workflows)

    result = wire_orphan_workflows(str(outdir))

    assert len(result["wired"]) == 1, result
    assert result["wired"][0]["workflow"] == "ScanProductWorkflow"
    assert result["wired"][0]["page_route"] == "/scan"
    assert result["unresolved"] == []

    # The Form's props.workflow now points at the api_event workflow.
    page = json.loads((outdir / "src" / "schemas" / "scan.json").read_text(encoding="utf-8"))
    form = page["root"]["children"][0]
    assert form["props"]["workflow"] == "ScanProductWorkflow"


# --------------------------------------------------------------------------- #
# Test 8 (VPS-M) — event-only (db_change/schedule/timer) workflows are NOT
# eligible orphans; wiring one to a form would misrepresent its dispatch.
# --------------------------------------------------------------------------- #

def test_wire_orphan_workflows_skips_event_only_triggers(tmp_path):
    from services.orphan_wiring_pass import _find_orphan_workflows

    pages = [
        # An unwired form with matching field names — the trigger gate is
        # the ONLY thing keeping the workflow off it.
        ("audit.json", _page("/audit", [_input("recordId")])),
    ]
    workflows = [
        _workflow(
            "NightlyAuditWorkflow",
            [{"name": "recordId", "type": "string", "required": True}],
            trigger={"type": "schedule", "cron": "0 0 * * *"},
        ),
        _workflow(
            "OnRowChangeWorkflow",
            [{"name": "recordId", "type": "string", "required": True}],
            trigger={"type": "db_change", "table": "orders"},
        ),
    ]
    outdir = _scaffold(tmp_path, pages, workflows)

    orphans = _find_orphan_workflows(str(outdir))
    # Neither event-only workflow appears — the gate refuses them so a
    # form-submit wire can never be attempted on a schedule/db_change wf.
    assert orphans == []
