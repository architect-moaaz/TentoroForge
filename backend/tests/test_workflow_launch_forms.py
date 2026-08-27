"""Tests for the trigger-input-form generator for bare-button workflow launchers.

A manual workflow whose ENTRY action is a db_insert, launched by a BARE Button
(props.workflow, not inside a Form), dispatches an EMPTY payload -> the insert's
{{col}} bindings resolve null -> NOT-NULL violation. The generator emits a
"trigger input form" page collecting the required inputs and repoints the launcher
button to NAVIGATE to that form (a <Form workflow="X"> dispatches the named values).
"""
import json
import re
from pathlib import Path

import pytest

from services.workflow_launch_forms import ensure_workflow_launch_forms


def _registry() -> dict:
    return {
        "entities": {
            "Interview": {
                "table": "interviews",
                "fields": {
                    "id": {"type": "uuid", "primaryKey": True, "nullable": False},
                    "applicationId": {"type": "uuid", "nullable": False},
                    "recruitmentDriveId": {"type": "uuid", "nullable": False},
                    "scheduledAt": {"type": "timestamp", "nullable": False},
                    "location": {"type": "varchar", "nullable": False},
                    "status": {"type": "varchar", "nullable": False, "hasDefault": True},
                    "createdAt": {"type": "timestamp", "hasDefault": True},
                },
            },
            "Application": {
                "table": "applications",
                "fields": {
                    "id": {"type": "uuid", "primaryKey": True, "nullable": False},
                    "fullName": {"type": "varchar"},
                },
            },
            "RecruitmentDrive": {
                "table": "recruitment_drives",
                "fields": {
                    "id": {"type": "uuid", "primaryKey": True, "nullable": False},
                    "title": {"type": "varchar"},
                },
            },
        },
        "relations": [],
    }


def _workflow() -> dict:
    return {
        "id": "interviewschedulingworkflow",
        "name": "InterviewSchedulingWorkflow",
        "description": "Schedule an interview for a shortlisted application.",
        "definition": {
            "trigger": {"type": "manual"},
            "steps": [],
            "nodes": [
                {"id": "trigger", "type": "trigger",
                 "data": {"nodeType": "trigger", "config": {"nodeType": "trigger"}}},
                {"id": "insert", "type": "action",
                 "data": {"label": "Create Interview", "nodeType": "action",
                          "config": {"actionType": "db_insert", "table": "interviews",
                                     "values": {
                                         "applicationId": "{{applicationId}}",
                                         "recruitmentDriveId": "{{recruitmentDriveId}}",
                                         "scheduledAt": "{{scheduledAt}}",
                                         "location": "{{location}}",
                                         "status": "{{status}}",
                                     }}}},
                {"id": "end", "type": "end", "data": {"nodeType": "end"}},
            ],
            "edges": [],
        },
    }


def _list_page() -> dict:
    return {
        "schemaVersion": "2",
        "id": "interviews-list",
        "route": "/interviews",
        "layout": "main",
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"}, "children": [
            {"type": "Row", "props": {"justify": "between"}, "children": [
                {"type": "Heading", "props": {"content": "Interviews", "level": 1}},
                {"type": "Button", "props": {
                    "label": "Schedule Interview",
                    "workflow": "interviewschedulingworkflow"}},
            ]},
            {"type": "Table", "props": {"columns": [], "rows": "{{interviews}}"}},
        ]},
    }


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    out = tmp_path / "app"
    (out / "workflows").mkdir(parents=True)
    (out / "src" / "schemas").mkdir(parents=True)
    (out / "registry.json").write_text(json.dumps(_registry(), indent=2))
    (out / "workflows" / "interviewschedulingworkflow.json").write_text(
        json.dumps(_workflow(), indent=2))
    (out / "src" / "schemas" / "interviews.json").write_text(
        json.dumps(_list_page(), indent=2))
    return out


def _find_nodes(node, typ, acc):
    if isinstance(node, list):
        for n in node:
            _find_nodes(n, typ, acc)
    elif isinstance(node, dict):
        if node.get("type") == typ:
            acc.append(node)
        for c in node.get("children") or []:
            _find_nodes(c, typ, acc)
        if "root" in node:
            _find_nodes(node["root"], typ, acc)
    return acc


# The launch form lives at a SINGLE-segment route `/<verb>-<entity>` so client-side
# navigation can never match an entity's `/[id]` detail pattern (which would open a
# phantom-record detail drawer instead of the form).
RUN_ROUTE = "/schedule-interview"
RUN_SLUG = "schedule-interview"


def test_launch_route_is_single_segment(app_dir):
    created = ensure_workflow_launch_forms(str(app_dir), _registry())
    assert created == [RUN_ROUTE]
    # exactly one path segment after the leading slash — no second `/`
    assert re.match(r"^/[^/]+$", created[0])
    lp = json.loads((app_dir / "src" / "schemas" / "interviews.json").read_text())
    btn = next(b for b in _find_nodes(lp["root"], "Button", [])
               if "Schedule" in str(b["props"].get("label", "")))
    assert btn["props"].get("navigate") == created[0]
    assert re.match(r"^/[^/]+$", btn["props"]["navigate"])


def test_run_page_and_form_workflow(app_dir):
    created = ensure_workflow_launch_forms(str(app_dir), _registry())
    assert RUN_ROUTE in created

    run_page = app_dir / "src" / "schemas" / f"{RUN_SLUG}.json"
    assert run_page.exists(), "run-page schema file should be created"
    sc = json.loads(run_page.read_text())
    forms = _find_nodes(sc["root"], "Form", [])
    assert len(forms) == 1
    assert forms[0]["props"]["workflow"] == "interviewschedulingworkflow"


def test_run_page_form_has_default_success_and_error_ux(app_dir):
    """The launch form must default to onSuccess = {toast, navigate:<parent>}
    and onError = {toast}. Silent post-submit ('button re-enables and stays
    put') is what made workflow-triggered forms feel broken in every
    generated app. Fix belongs in the emitter (belt) + library runtime
    (suspenders), both of which land in the same slice."""
    ensure_workflow_launch_forms(str(app_dir), _registry())
    sc = json.loads((app_dir / "src" / "schemas" / f"{RUN_SLUG}.json").read_text())
    forms = _find_nodes(sc["root"], "Form", [])
    assert len(forms) == 1
    props = forms[0]["props"]

    # onSuccess must carry BOTH toast + navigate.
    onSuccess = props.get("onSuccess")
    assert isinstance(onSuccess, dict), "Form is missing onSuccess"
    assert isinstance(onSuccess.get("toast"), str) and onSuccess["toast"], (
        "onSuccess.toast must be a non-empty string"
    )
    # Navigate must point at the entity's collection route (one level up
    # from the launch page — the /schedule-assessment → / rule for
    # single-segment launch routes, or /<seg> for parent-list flows).
    assert isinstance(onSuccess.get("navigate"), str) and onSuccess["navigate"].startswith("/"), (
        "onSuccess.navigate must be an absolute path"
    )

    # onError toast must be present so failures aren't silent either.
    onError = props.get("onError")
    assert isinstance(onError, dict), "Form is missing onError"
    assert isinstance(onError.get("toast"), str) and onError["toast"], (
        "onError.toast must be a non-empty string"
    )


def test_run_page_fields(app_dir):
    ensure_workflow_launch_forms(str(app_dir), _registry())
    sc = json.loads((app_dir / "src" / "schemas" / f"{RUN_SLUG}.json").read_text())

    selects = {n["props"].get("name"): n for n in _find_nodes(sc["root"], "Select", [])}
    dates = {n["props"].get("name"): n for n in _find_nodes(sc["root"], "DatePicker", [])}
    inputs = {n["props"].get("name"): n for n in _find_nodes(sc["root"], "Input", [])}

    # applicationId -> FK Select with an optionsFrom.source, and required
    assert "applicationId" in selects
    assert selects["applicationId"]["props"].get("optionsFrom", {}).get("source")
    assert selects["applicationId"]["props"].get("validators", {}).get("required") is True
    # recruitmentDriveId -> FK Select
    assert "recruitmentDriveId" in selects
    # scheduledAt -> DatePicker
    assert "scheduledAt" in dates
    # status is optional (hasDefault) — present but NOT required
    all_names = set(selects) | set(dates) | set(inputs)
    assert "status" in all_names
    status_node = inputs.get("status") or selects.get("status")
    assert status_node is not None
    assert status_node["props"].get("validators", {}).get("required") is not True
    # id / createdAt are never collected
    assert "id" not in all_names
    assert "createdAt" not in all_names


def test_launcher_button_repointed(app_dir):
    ensure_workflow_launch_forms(str(app_dir), _registry())
    sc = json.loads((app_dir / "src" / "schemas" / "interviews.json").read_text())
    buttons = _find_nodes(sc["root"], "Button", [])
    launcher = next(b for b in buttons if "Schedule" in str(b["props"].get("label", "")))
    assert launcher["props"].get("navigate") == RUN_ROUTE
    assert "workflow" not in launcher["props"]


def test_registry_ts_has_route(app_dir):
    ensure_workflow_launch_forms(str(app_dir), _registry())
    registry_ts = (app_dir / "src" / "schemas" / "registry.ts").read_text()
    assert f'"{RUN_ROUTE}"' in registry_ts


def test_idempotent(app_dir):
    first = ensure_workflow_launch_forms(str(app_dir), _registry())
    assert first == [RUN_ROUTE]
    before = (app_dir / "src" / "schemas" / "interviews.json").read_text()
    second = ensure_workflow_launch_forms(str(app_dir), _registry())
    assert second == []
    after = (app_dir / "src" / "schemas" / "interviews.json").read_text()
    assert before == after


# ── Bug 1: only ENTRY-insert workflows qualify ───────────────────────────────

def _approval_workflow() -> dict:
    """Entry action is db_update (acts on an existing row); the db_insert is a
    DOWNSTREAM audit-log write. Such a workflow must NOT be repointed."""
    return {
        "id": "orderapprovalworkflow",
        "name": "OrderApprovalWorkflow",
        "description": "Approve an existing order.",
        "definition": {
            "trigger": {"type": "manual"},
            "steps": [],
            "nodes": [
                {"id": "trigger", "type": "trigger",
                 "data": {"nodeType": "trigger", "config": {"nodeType": "trigger"}}},
                {"id": "update", "type": "action",
                 "data": {"nodeType": "action", "config": {
                     "actionType": "db_update", "table": "orders",
                     "values": {"status": "{{status}}"}, "where": {"id": "{{orderId}}"}}}},
                {"id": "audit", "type": "action",
                 "data": {"nodeType": "action", "config": {
                     "actionType": "db_insert", "table": "audit_logs",
                     "values": {"orderId": "{{orderId}}", "action": "{{action}}"}}}},
                {"id": "end", "type": "end", "data": {"nodeType": "end"}},
            ],
            "edges": [
                {"id": "e1", "source": "trigger", "target": "update", "data": {"edgeType": "default"}},
                {"id": "e2", "source": "update", "target": "audit", "data": {"edgeType": "default"}},
                {"id": "e3", "source": "audit", "target": "end", "data": {"edgeType": "default"}},
            ],
        },
    }


def _approval_page() -> dict:
    return {
        "schemaVersion": "2", "id": "orders-list", "route": "/orders", "layout": "main",
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {
                "label": "Approve Order", "workflow": "orderapprovalworkflow"}},
        ]},
    }


def test_entry_db_update_workflow_not_repointed(tmp_path):
    out = tmp_path / "app"
    (out / "workflows").mkdir(parents=True)
    (out / "src" / "schemas").mkdir(parents=True)
    reg = _registry()
    reg["entities"]["Order"] = {"table": "orders", "fields": {
        "id": {"type": "uuid", "primaryKey": True}, "status": {"type": "varchar"}}}
    reg["entities"]["AuditLog"] = {"table": "audit_logs", "fields": {
        "id": {"type": "uuid", "primaryKey": True},
        "orderId": {"type": "uuid", "nullable": False},
        "action": {"type": "varchar", "nullable": False}}}
    (out / "workflows" / "orderapprovalworkflow.json").write_text(json.dumps(_approval_workflow()))
    (out / "src" / "schemas" / "orders.json").write_text(json.dumps(_approval_page()))

    created = ensure_workflow_launch_forms(str(out), reg)

    assert created == []
    # button is left completely alone
    sc = json.loads((out / "src" / "schemas" / "orders.json").read_text())
    btn = _find_nodes(sc["root"], "Button", [])[0]
    assert btn["props"].get("workflow") == "orderapprovalworkflow"
    assert "navigate" not in btn["props"]
    # no form page was created for the downstream insert's table
    assert not (out / "src" / "schemas" / "audit_logs").exists()
    assert not (out / "src" / "schemas" / "orders" / "approve.json").exists()


# ── Bug 2: never overwrite a pre-existing non-workflow page ───────────────────

def test_collision_with_existing_real_page(app_dir):
    # A hand-authored real page already occupies the single-segment route the pass
    # would derive (a top-level file).
    real = app_dir / "src" / "schemas" / f"{RUN_SLUG}.json"
    real_content = json.dumps({
        "schemaVersion": "2", "id": "hand-authored", "route": RUN_ROUTE,
        "layout": "main", "root": {"type": "Heading", "props": {"content": "MINE"}}}, indent=2)
    real.write_text(real_content)

    created = ensure_workflow_launch_forms(str(app_dir), _registry())

    # the real page is untouched
    assert real.read_text() == real_content
    # the generated form landed at a suffixed route instead
    assert created == [f"{RUN_ROUTE}-2"]
    suffixed = app_dir / "src" / "schemas" / f"{RUN_SLUG}-2.json"
    assert suffixed.exists()
    sc = json.loads(suffixed.read_text())
    assert _find_nodes(sc["root"], "Form", [])[0]["props"]["workflow"] == "interviewschedulingworkflow"
    # the launcher points at the suffixed route
    lp = json.loads((app_dir / "src" / "schemas" / "interviews.json").read_text())
    btn = next(b for b in _find_nodes(lp["root"], "Button", [])
               if "Schedule" in str(b["props"].get("label", "")))
    assert btn["props"].get("navigate") == f"{RUN_ROUTE}-2"
