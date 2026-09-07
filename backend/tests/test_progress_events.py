"""Structured deliverable-progress events power the generation UI's live
preview cards. Summaries must be compact + I/O-safe."""
import json

from services.progress_events import (
    resource_event,
    summarize_entity,
    summarize_workflow,
    summarize_page,
    iter_entities,
    iter_workflows,
    iter_pages,
)


def test_resource_event_shape():
    ev = resource_event("page", "/x", "in_progress", index=2, total=5, summary="Table · 3 nodes")
    assert ev == {"kind": "page", "name": "/x", "state": "in_progress",
                  "index": 2, "total": 5, "summary": "Table · 3 nodes"}


def test_summarize_entity_counts_fields_and_fks():
    ent = {"fields": [
        {"name": "id"}, {"name": "patientId", "references": "patients"},
        {"name": "dentistId"}, {"name": "notes"},
    ]}
    s = summarize_entity(ent)
    assert "4 fields" in s
    assert "patient" in s and "dentist" in s


def test_summarize_workflow_reports_trigger_and_steps():
    wf = {"definition": {
        "trigger": {"type": "api_event", "event": "appointment_status_change"},
        "nodes": [{"type": "trigger"}, {"type": "condition"}, {"type": "action"}, {"type": "end"}],
    }}
    s = summarize_workflow(wf)
    assert "appointment status change" in s
    assert "2 steps" in s          # condition + action (trigger/end excluded)


def test_summarize_page_lists_notable_components_and_node_count():
    schema = {"root": {"type": "Stack", "children": [
        {"type": "Heading"}, {"type": "Table"}, {"type": "Form"},
    ]}}
    s = summarize_page(schema)
    assert "Table" in s and "Form" in s
    assert "nodes" in s


def test_iter_entities_reads_registry(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({"entities": {
        "Appointment": {"fields": [{"name": "id"}, {"name": "patientId"}]},
        "Patient": {"fields": [{"name": "id"}]},
    }}), encoding="utf-8")
    evs = list(iter_entities(str(tmp_path)))
    assert [e["name"] for e in evs] == ["Appointment", "Patient"]
    assert evs[0]["total"] == 2 and evs[0]["index"] == 1
    assert evs[0]["kind"] == "data_model"


def test_iter_workflows_splits_domain_and_crud(tmp_path):
    wdir = tmp_path / "workflows"
    wdir.mkdir()
    (wdir / "AppointmentStatusWorkflow.json").write_text(json.dumps({
        "name": "AppointmentStatusWorkflow",
        "definition": {"trigger": {"type": "api_event", "event": "x"},
                       "nodes": [{"type": "action"}]},
    }), encoding="utf-8")
    (wdir / "CreatePatient.json").write_text(json.dumps({"name": "CreatePatient"}), encoding="utf-8")
    (wdir / "DeletePatient.json").write_text(json.dumps({"name": "DeletePatient"}), encoding="utf-8")
    evs = list(iter_workflows(str(tmp_path)))
    assert evs[0]["name"] == "AppointmentStatusWorkflow"
    assert evs[-1]["name"] == "2 CRUD workflows"     # rollup, not enumerated
    assert all(e["kind"] == "workflow" for e in evs)


def test_iter_pages_skips_shell_and_navflow(tmp_path):
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    (sdir / "shell.json").write_text("{}", encoding="utf-8")
    (sdir / "nav-flow.json").write_text("{}", encoding="utf-8")
    (sdir / "appointments.json").write_text(json.dumps(
        {"route": "/appointments", "root": {"type": "Stack", "children": [{"type": "Table"}]}}), encoding="utf-8")
    evs = list(iter_pages(str(tmp_path)))
    assert len(evs) == 1
    assert evs[0]["name"] == "/appointments"


def test_readers_missing_dirs_are_safe(tmp_path):
    assert list(iter_entities(str(tmp_path))) == []
    assert list(iter_workflows(str(tmp_path))) == []
    assert list(iter_pages(str(tmp_path))) == []
