"""Seam 1: an approval/review workflow must auto-start when its entity is created,
so the workflow pauses at the approval node and a task exists for the manager to
resolve. The contract generator infers the approval workflow (approve/reject/review
keywords) + its entity (name match in the trigger/description) and binds
`<entity>_created → workflow`. Plan workflows at contract time are lightweight
({name, trigger, description, steps}) — no nodes, no explicit entity."""
import json

from services.contract_generator import _generate_event_bindings


def _plan():
    return {
        "entities": [{"name": "LeaveRequest"}, {"name": "User"}],
        "workflows": [{
            "name": "LeaveReviewWorkflow",
            "trigger": "Manager clicks approve or reject on leave request",
            "description": "Updates leave request status and notifies the employee",
            "steps": ["Update request status to approved or rejected"],
        }],
        "api_strategy": {},
    }


def test_binds_created_event_to_the_approval_workflow(tmp_path):
    out = tmp_path / "event-bindings.json"
    _generate_event_bindings(out, _plan())
    cfg = json.loads(out.read_text(encoding="utf-8"))
    created = [b for b in cfg["bindings"] if b["event"] == "leaverequest_created"]
    assert created, cfg
    assert "LeaveReviewWorkflow" in created[0]["workflows"]
    assert created[0]["source"] == "data:leaverequest:create"


def test_non_approval_workflow_is_not_created_bound(tmp_path):
    plan = {
        "entities": [{"name": "Invoice"}],
        "workflows": [{
            "name": "NightlyReport",
            "trigger": "Runs on a nightly cron",
            "description": "Emails a summary report",
            "steps": ["Aggregate invoices", "Email the report"],
        }],
        "api_strategy": {},
    }
    out = tmp_path / "eb.json"
    _generate_event_bindings(out, plan)
    cfg = json.loads(out.read_text(encoding="utf-8"))
    assert not [b for b in cfg["bindings"] if b["event"] == "invoice_created"]


def test_approval_workflow_without_a_matching_entity_is_skipped(tmp_path):
    # Approval-like but names no known entity → no created-binding (can't infer target).
    plan = {
        "entities": [{"name": "Invoice"}],
        "workflows": [{
            "name": "GenericApproval",
            "trigger": "Someone approves something",
            "description": "A review step",
            "steps": [],
        }],
        "api_strategy": {},
    }
    out = tmp_path / "eb.json"
    _generate_event_bindings(out, plan)
    cfg = json.loads(out.read_text(encoding="utf-8"))
    assert not [b for b in cfg["bindings"] if b["event"].endswith("_created")]


def test_created_binding_not_duplicated(tmp_path):
    out = tmp_path / "eb.json"
    _generate_event_bindings(out, _plan())
    cfg = json.loads(out.read_text(encoding="utf-8"))
    created = [b for b in cfg["bindings"] if b["event"] == "leaverequest_created"]
    assert len(created) == 1
