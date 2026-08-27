"""Slice E T6 — ``submit.kind = "workflow_resume"`` extension.

The /tasks/[id] task-completion form (Slice E T2) submits its decision
back to /api/workflows/[wfId]/execute with a taskId in the body — the
existing route handles resume when taskId is present. To describe
this pattern in the plan (so the deterministic form scaffolder +
validator can enforce it), Slice A's SUBMIT-AUTHORITY contract gains
a new ``kind``:

    page.submit = {
        "kind":    "workflow_resume",
        "target":  "<workflow name being resumed>",
        "task_id": {"kind": "route", "param": "id"},
    }

Notes:
- ``task_id.kind`` must be ``"route"`` — the /tasks/[id] page reads
  the id from the URL. Other kinds are rejected.
- ``target`` still refers to a real workflow name. This is a
  RESUME, not a fresh dispatch.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# resolve_page_submit preserves the new kind + task_id
# ─────────────────────────────────────────────────────────────────────

def test_resolve_page_submit_preserves_workflow_resume_kind():
    from services.submit_authority import resolve_page_submit

    plan = {
        "pages": [
            {
                "name": "TaskDetail",
                "route": "/tasks/[id]",
                "submit": {
                    "kind": "workflow_resume",
                    "target": "ApprovalWorkflow",
                    "task_id": {"kind": "route", "param": "id"},
                },
            }
        ]
    }
    got = resolve_page_submit(plan, "TaskDetail")
    assert got is not None
    assert got["kind"] == "workflow_resume"
    assert got["target"] == "ApprovalWorkflow"
    # task_id preserved verbatim so the form scaffolder can use it.
    assert got["task_id"] == {"kind": "route", "param": "id"}


def test_resolve_page_submit_workflow_resume_without_task_id_returns_none_task_id():
    """A workflow_resume without an explicit task_id defaults to
    route:id — the /tasks/[id] convention."""
    from services.submit_authority import resolve_page_submit

    plan = {
        "pages": [
            {
                "name": "TaskDetail",
                "route": "/tasks/[id]",
                "submit": {
                    "kind": "workflow_resume",
                    "target": "ApprovalWorkflow",
                },
            }
        ]
    }
    got = resolve_page_submit(plan, "TaskDetail")
    assert got["kind"] == "workflow_resume"
    assert got["task_id"] == {"kind": "route", "param": "id"}


# ─────────────────────────────────────────────────────────────────────
# plan_validator flags invalid workflow_resume declarations
# ─────────────────────────────────────────────────────────────────────

def test_plan_validator_rejects_non_route_task_id_kind():
    from services.plan_validator import _rule_workflow_resume_task_id

    plan = {
        "pages": [
            {
                "name": "TaskDetail",
                "route": "/tasks/[id]",
                "submit": {
                    "kind": "workflow_resume",
                    "target": "W",
                    "task_id": {"kind": "form_field", "field": "hidden_task_id"},
                },
            }
        ],
        "workflows": [{"name": "W"}],
    }
    errs = _rule_workflow_resume_task_id(plan)
    assert errs, "validator did not flag non-route task_id"
    assert any("workflow_resume" in e.get("message", "").lower() for e in errs)


def test_plan_validator_accepts_route_task_id():
    from services.plan_validator import _rule_workflow_resume_task_id

    plan = {
        "pages": [
            {
                "name": "TaskDetail",
                "route": "/tasks/[id]",
                "submit": {
                    "kind": "workflow_resume",
                    "target": "W",
                    "task_id": {"kind": "route", "param": "id"},
                },
            }
        ],
        "workflows": [{"name": "W"}],
    }
    assert _rule_workflow_resume_task_id(plan) == []


def test_plan_validator_rejects_route_task_id_param_not_in_route():
    """A workflow_resume declaring task_id.param='someOther' when the
    page's route only has [id] is nonsensical — the runtime would find
    no such param."""
    from services.plan_validator import _rule_workflow_resume_task_id

    plan = {
        "pages": [
            {
                "name": "TaskDetail",
                "route": "/tasks/[id]",
                "submit": {
                    "kind": "workflow_resume",
                    "target": "W",
                    "task_id": {"kind": "route", "param": "notInRoute"},
                },
            }
        ],
        "workflows": [{"name": "W"}],
    }
    errs = _rule_workflow_resume_task_id(plan)
    assert errs
    assert any("notInRoute" in e.get("message", "") for e in errs)


def test_plan_validator_rejects_workflow_resume_target_that_does_not_exist():
    from services.plan_validator import _rule_workflow_resume_task_id

    plan = {
        "pages": [
            {
                "name": "TaskDetail",
                "route": "/tasks/[id]",
                "submit": {
                    "kind": "workflow_resume",
                    "target": "PhantomWorkflow",
                    "task_id": {"kind": "route", "param": "id"},
                },
            }
        ],
        "workflows": [{"name": "OtherWorkflow"}],
    }
    errs = _rule_workflow_resume_task_id(plan)
    assert errs
    assert any("PhantomWorkflow" in e.get("message", "") for e in errs)


# ─────────────────────────────────────────────────────────────────────
# form_target_guard tolerates the new kind
# ─────────────────────────────────────────────────────────────────────

def test_form_target_guard_accepts_workflow_resume_kind(tmp_path):
    """The output-side guard walks generated page schemas and flags
    forms without a submit target. It currently accepts kind=workflow
    and kind=data_api; must also accept kind=workflow_resume."""
    from services.submit_authority_guards import form_target_guard
    import json

    contracts = tmp_path / "contracts"
    contracts.mkdir()
    plan = {
        "pages": [
            {
                "name": "TaskDetail",
                "route": "/tasks/[id]",
                "submit": {
                    "kind": "workflow_resume",
                    "target": "ApprovalWorkflow",
                    "task_id": {"kind": "route", "param": "id"},
                },
            }
        ],
        "workflows": [{"name": "ApprovalWorkflow"}],
    }
    (contracts / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    # Schema tree with a Form so the guard has something to scan.
    schemas = contracts / "page-schemas"
    schemas.mkdir()
    (schemas / "tasks-id.json").write_text(json.dumps({
        "route": "/tasks/[id]",
        "page": {
            "children": [
                {
                    "component": "Form",
                    "props": {},
                    "children": [
                        {"component": "Input", "props": {"name": "comment"}}
                    ],
                }
            ]
        }
    }), encoding="utf-8")

    out = form_target_guard(str(tmp_path))
    # No violation — the workflow_resume-kind form is well-declared.
    for v in out.get("violations", []):
        assert v.get("route") != "/tasks/[id]", (
            f"form_target_guard falsely flagged workflow_resume form: {v}"
        )
