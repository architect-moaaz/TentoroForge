"""Slice 1 of BusinessLogic→deterministic: `_build_step_config` must produce
EXECUTABLE db configs from the real schema (registry) — a `create` step becomes a
real db_insert into the entity's table with its columns bound, not a dead
`db_query` with a SQL comment."""
from services.workflow_generator import _build_step_config


_MODELS = {
    "Applicant": {
        "name": "Applicant",
        "fields": [
            {"name": "id", "primaryKey": True},
            {"name": "fullName"},
            {"name": "email"},
            {"name": "status"},
            {"name": "recruiterId"},  # FK — set by the app, not part of the insert values
        ],
    }
}
_TABLES = {"applicants", "users"}


def test_create_action_builds_executable_db_insert():
    wf = {"name": "Applicant Intake", "description": "process new applicants"}
    cfg = _build_step_config("Create applicant record", "action", wf, _MODELS, _TABLES)
    assert cfg["actionType"] == "db_insert"
    assert cfg["table"] == "applicants"                       # real table, snake-plural
    # editable columns bound to workflow vars; PK + FK dropped
    assert cfg["values"] == {
        "fullName": "{{fullName}}", "email": "{{email}}", "status": "{{status}}",
    }
    assert "id" not in cfg["values"] and "recruiterId" not in cfg["values"]
    assert "-- " not in str(cfg)                               # no SQL-comment stub


def test_update_action_builds_executable_db_update():
    wf = {"name": "Applicant Intake", "description": "process applicants"}
    cfg = _build_step_config("Update applicant status", "action", wf, _MODELS, _TABLES)
    assert cfg["actionType"] == "db_update"
    assert cfg["table"] == "applicants"
    assert cfg.get("where")                                    # must target a row
    assert cfg.get("values")                                   # must set something


def test_send_step_has_recipient_and_body():
    wf = {"name": "Applicant Intake", "description": ""}
    cfg = _build_step_config("Notify recruiter of new applicant", "action", wf, _MODELS, _TABLES)
    assert cfg["actionType"] in ("send_notification", "send_email")
    # executable: must carry a recipient AND a message/body (not prose-only)
    assert any(k in cfg for k in ("recipientRole", "recipient", "to"))
    assert any(k in cfg for k in ("message", "body"))


def test_degrades_when_no_table_resolves():
    """Unknown entity / no tables → still returns a valid, executable node (never a
    dead db_query comment)."""
    wf = {"name": "Mystery Flow", "description": ""}
    cfg = _build_step_config("Create widget", "action", wf, {}, set())
    # no real table to insert into → fall back to a harmless progress marker
    assert cfg["actionType"] in ("set_variable", "db_insert")
    assert "-- " not in str(cfg)


def test_backward_compatible_without_table_names():
    """table_names is optional — existing callers that don't pass it still work."""
    wf = {"name": "X", "description": ""}
    cfg = _build_step_config("Validate the fields", "condition", wf, {})
    assert cfg.get("expression")
