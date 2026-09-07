"""The context-engine workflow catalog hands the page agent the REAL workflow
names so it references them instead of inventing dead refs like confirmAppointment."""
import json

from services.context_assembler import workflow_catalog_block


def _wf(tmp_path, obj, fname):
    wdir = tmp_path / "workflows"
    wdir.mkdir(exist_ok=True)
    (wdir / fname).write_text(json.dumps(obj), encoding="utf-8")


def test_no_workflows_dir_is_empty(tmp_path):
    assert workflow_catalog_block(tmp_path) == ""


def test_lists_domain_workflows_and_summarizes_crud(tmp_path):
    _wf(tmp_path, {
        "name": "AppointmentStatusWorkflow",
        "description": "Transitions appointment status.\nsecond line ignored",
        "processVariables": [
            {"name": "appointmentId", "required": True},
            {"name": "targetStatus", "required": True},
            {"name": "note", "required": False},
        ],
    }, "6ae8ad74.json")
    _wf(tmp_path, {"name": "CreateAppointment"}, "CreateAppointment.json")
    _wf(tmp_path, {"name": "UpdateAppointment"}, "UpdateAppointment.json")
    _wf(tmp_path, {"name": "DeletePatient"}, "DeletePatient.json")

    block = workflow_catalog_block(tmp_path)
    # Domain workflow listed with its required inputs (optional 'note' excluded).
    assert "`AppointmentStatusWorkflow`" in block
    assert "inputs: appointmentId, targetStatus" in block
    assert "note" not in block
    # CRUD workflows are summarized, not enumerated by name.
    assert "CreateAppointment" not in block
    assert "3 total" in block
    # The anti-invention instruction is present.
    assert "NEVER invent" in block


def test_only_crud_still_renders_summary(tmp_path):
    _wf(tmp_path, {"name": "CreatePatient"}, "CreatePatient.json")
    block = workflow_catalog_block(tmp_path)
    assert "1 total" in block
    assert "Domain workflows:" not in block
