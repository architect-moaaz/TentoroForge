"""When workflow_launch_forms generates a launch-form page + repoints a button,
it must also register the new page (as a node) and the incoming button-edge in
`src/contracts/nav-flow.json` — so the editor nav-graph, the source-page button,
and the schema on disk all agree. Drift here shows up as a page that runtime can
reach but the editor's nav-graph doesn't show (the /schedule-assessment case in
mc2xgclv)."""
from __future__ import annotations

import json
from pathlib import Path

from services.workflow_launch_forms import ensure_workflow_launch_forms


def _write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _mc_shaped_app(tmp: Path) -> tuple[dict, Path]:
    """A minimal mc2xgclv-shaped fixture: an /assessments page with a bare
    Schedule Assessment button + a domain workflow whose entry is a db_insert."""
    out = tmp / "app"
    schemas = out / "src" / "schemas"
    workflows = out / "workflows"

    _write(schemas / "assessments.json", {
        "route": "/assessments",
        "schemaVersion": "2",
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {
                "label": "Schedule Assessment",
                "workflow": "assessmentschedulingworkflow",
            }},
        ]},
    })
    _write(workflows / "assessmentschedulingworkflow.json", {
        "name": "AssessmentSchedulingWorkflow",
        "definition": {"nodes": [
            {"id": "create_assessment_record",
             "type": "action",
             "data": {"label": "Create Assessment Record",
                      "config": {"actionType": "db_insert", "table": "assessments",
                                 "values": {"applicationId": "{{applicationId}}",
                                            "candidateId": "{{candidateId}}",
                                            "assessmentType": "{{assessmentType}}",
                                            "scheduledAt": "{{scheduledAt}}"}}}},
        ]},
    })
    registry = {"entities": {
        "Assessment": {"name": "Assessment", "slug": "assessments", "table": "assessments",
                       "fields": {
                           "id": {"type": "uuid", "primaryKey": True},
                           "applicationId": {"type": "uuid", "notNull": True},
                           "candidateId": {"type": "uuid", "notNull": True},
                           "assessmentType": {"type": "varchar", "notNull": True},
                           "scheduledAt": {"type": "timestamp", "notNull": True},
                       }},
    }}
    return registry, out


def test_launch_form_registers_page_and_edge_in_nav_flow(tmp_path):
    registry, out = _mc_shaped_app(tmp_path)
    created = ensure_workflow_launch_forms(str(out), registry)
    assert created, "expected at least one launch-form to be created"
    form_route = created[0]

    # (a) The form schema exists on disk.
    form_slug = form_route.lstrip("/")
    assert (out / "src" / "schemas" / f"{form_slug}.json").exists()

    # (b) The source button was repointed to navigate to that route.
    src = json.loads((out / "src" / "schemas" / "assessments.json").read_text())
    btn = src["root"]["children"][0]
    assert btn["props"].get("navigate") == form_route
    assert "workflow" not in btn["props"]

    # (c) nav-flow.json exists and now has a node for the new route + an incoming edge.
    nav_path = out / "src" / "contracts" / "nav-flow.json"
    assert nav_path.exists(), "nav-flow.json should have been synthesized"
    nav = json.loads(nav_path.read_text())
    pages = nav["pages"]
    routes = [p.get("route") for p in pages]
    assert form_route in routes, f"expected {form_route} node in nav-flow pages; got {routes}"
    # Confirm the launch-form's page node has the fields the editor consumes.
    form_node = next(p for p in pages if p.get("route") == form_route)
    assert form_node.get("id")
    assert form_node.get("schemaFile") == f"src/schemas/{form_slug}.json"

    # An edge from /assessments → the form, triggered by the button label.
    tx = nav["transitions"]
    src_id = next(p["id"] for p in pages if p.get("route") == "/assessments")
    target_id = form_node["id"]
    matching = [t for t in tx
                if t.get("from") == src_id and t.get("to") == target_id
                and "Schedule Assessment" in str(t.get("trigger", ""))]
    assert matching, f"expected an edge {src_id!r} -> {target_id!r} with a button trigger; got {tx}"


def test_launch_form_nav_flow_registration_is_idempotent(tmp_path):
    registry, out = _mc_shaped_app(tmp_path)
    ensure_workflow_launch_forms(str(out), registry)
    nav1 = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())
    # Second run: no new nodes/edges added.
    ensure_workflow_launch_forms(str(out), registry)
    nav2 = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())
    assert len(nav2["pages"]) == len(nav1["pages"])
    assert len(nav2["transitions"]) == len(nav1["transitions"])


def test_no_launch_forms_leaves_nav_flow_untouched(tmp_path):
    """A page without a bare-button launcher shouldn't cause nav-flow.json to
    exist just because the pass ran."""
    out = tmp_path / "app"
    _write(out / "src" / "schemas" / "home.json", {"route": "/", "root": {"type": "Stack"}})
    ensure_workflow_launch_forms(str(out), {"entities": {}})
    assert not (out / "src" / "contracts" / "nav-flow.json").exists()
