# backend/tests/test_form_model_correctness.py
import json

from services.deterministic_pages import _editable_columns, _input_for
from services.create_page_coverage import build_create_page
from services.semantic_field_types import _decide, harvest_workflow_statuses

_APP_COLS = {
    "id": {"type": "uuid", "primaryKey": True},
    "candidateId": {"type": "uuid", "nullable": False},
    "status": {"type": "varchar", "nullable": False, "hasDefault": True},
    "keywordScore": {"type": "integer", "nullable": False},
    "shortlistedAt": {"type": "timestamp", "nullable": True},
    "rejectedAt": {"type": "timestamp", "nullable": True},
    "createdAt": {"type": "timestamp", "nullable": False, "hasDefault": True},
}

def test_editable_columns_drops_lifecycle_timestamps():
    cols = dict(_editable_columns(_APP_COLS))
    assert "shortlistedAt" not in cols and "rejectedAt" not in cols   # lifecycle → excluded
    assert "createdAt" not in cols                                    # system → excluded
    assert "candidateId" in cols and "status" in cols and "keywordScore" in cols

def test_required_number_gets_validators():
    node = _input_for("keywordScore", {"type": "integer", "nullable": False})
    assert node["type"] == "NumberInput"
    assert node["props"].get("validators", {}).get("required") is True


# --- Task 2: build_create_page delegates to the registry-driven build_form_page ---

_ENTITIES = {
    "Application": {"fields": {
        "id": {"type": "uuid", "primaryKey": True},
        "candidateId": {"type": "uuid", "nullable": False},
        "recruitmentDriveId": {"type": "uuid", "nullable": False},
        "status": {"type": "varchar", "nullable": False, "hasDefault": True},
        "pipelineStage": {"type": "varchar", "nullable": False},
        "keywordScore": {"type": "integer", "nullable": True},
        "shortlistedAt": {"type": "timestamp", "nullable": True},
    }},
    "Candidate": {"fields": {"id": {"type": "uuid", "primaryKey": True}, "fullName": {"type": "varchar"}}},
    "RecruitmentDrive": {"fields": {"id": {"type": "uuid", "primaryKey": True}, "title": {"type": "varchar"}}},
}


def _nodes(page):
    found = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") in ("Input", "Select", "NumberInput", "DatePicker", "Textarea", "Switch", "KeyValueInput"):
                found.append(n)
            for c in (n.get("children") or []):
                walk(c)
            for c in ([n.get("root")] if n.get("root") else []):
                walk(c)
    walk(page)
    return found


def test_build_create_page_is_field_model_correct():
    cols = _ENTITIES["Application"]["fields"]
    page = build_create_page("/applications/new", "Application", cols, "CreateApplication", _ENTITIES)
    by = {n["props"]["name"]: n for n in _nodes(page) if n["props"].get("name")}
    # FK → relational Select with optionsFrom, NOT a DatePicker/text
    assert by["candidateId"]["type"] == "Select"
    assert by["candidateId"]["props"]["optionsFrom"]["source"]  # e.g. "candidates"
    assert by["recruitmentDriveId"]["type"] == "Select"
    # enum-ish varchar stays Input/Select — NEVER a NumberInput
    assert by["pipelineStage"]["type"] != "NumberInput"
    # required (notNull, no default) → validators.required present
    assert by["candidateId"]["props"].get("validators", {}).get("required") is True
    # lifecycle timestamp excluded
    assert "shortlistedAt" not in by
    # a Card wraps the form (layout)
    assert '"Card"' in json.dumps(page)


# --- Task 3: _decide is FK-aware, type-first, and anchored ---

def test_fk_column_not_retyped_to_datepicker():
    # candidateId must NOT become a DatePicker (the "candiDATE" substring bug)
    kind, _ = _decide("candidateId", "uuid", options=None)
    assert kind != "DatePicker"


def test_fk_column_left_for_relational_builder():
    # An FK is left untouched (None) so the FK-aware scaffold makes a relational Select.
    assert _decide("candidateId", "uuid", options=None) == (None, None)
    assert _decide("recruitmentDriveId", "uuid", options=None) == (None, None)


def test_enum_varchar_not_retyped_to_number():
    # pipelineStage must NOT become a NumberInput (the "stAGE" substring bug)
    kind, _ = _decide("pipelineStage", "varchar", options=None)
    assert kind != "NumberInput"


def test_real_date_still_datepicker():
    kind, _ = _decide("startDate", "timestamp", options=None)
    assert kind == "DatePicker"


def test_real_quantity_still_number():
    kind, _ = _decide("keywordScore", "integer", options=None)
    assert kind == "NumberInput"


def test_stage_message_image_not_number_or_date():
    # "stage"/"message"/"image" contain "age"/"age"/"age" mid-word — must not fire qty/date.
    for name in ("stage", "message", "image"):
        kind, _ = _decide(name, "varchar", options=None)
        assert kind not in ("NumberInput", "DatePicker"), f"{name} -> {kind}"


def test_amount_quantity_age_still_number_by_name():
    # Real quantity words still map to NumberInput when the SQL type is unknown/varchar.
    for name in ("amount", "quantity", "age", "score"):
        kind, _ = _decide(name, "varchar", options=None)
        assert kind == "NumberInput", f"{name} -> {kind}"


def test_bool_name_true_positives():
    for n in ("isActive", "hasAccess", "canEdit", "is_active", "isPublished", "featuredFlag", "archived"):
        assert _decide(n, "varchar", None)[0] == "Switch", n


def test_bool_name_no_false_positive_on_varchar_words():
    for n in ("candidateName", "cancelReason", "issueTitle", "status", "description", "hasty"):
        assert _decide(n, "varchar", None)[0] != "Switch", n


def test_real_boolean_type_still_switch():
    assert _decide("flag", "boolean", None)[0] == "Switch"


# --- FM-G2: enum -> Select (registry enum_values + workflow-status harvest) ---

def test_input_for_enum_values_becomes_select():
    node = _input_for("status", {"type": "varchar", "nullable": False, "enum_values": ["Open", "Closed"]})
    assert node["type"] == "Select"
    assert [o["value"] for o in node["props"]["options"]] == ["Open", "Closed"]
    assert node["props"].get("validators", {}).get("required") is True


def test_decide_status_with_options_is_select():
    kind, props = _decide("status", "varchar", ["Applied", "Screening", "Offer"])
    assert kind == "Select"
    assert [o["value"] for o in props["options"]] == ["Applied", "Screening", "Offer"]


# --- control is derived via the shared resolve_control authority ---

def test_input_for_derives_control_via_resolve_control():
    # varchar → Input
    assert _input_for("title", {"type": "varchar"})["type"] == "Input"
    # integer → NumberInput
    assert _input_for("count", {"type": "integer"})["type"] == "NumberInput"
    # timestamp → DatePicker
    assert _input_for("dueOn", {"type": "timestamp"})["type"] == "DatePicker"
    # boolean → Switch
    assert _input_for("active", {"type": "boolean"})["type"] == "Switch"
    # long text → Textarea
    assert _input_for("body", {"type": "text"})["type"] == "Textarea"
    # jsonb → KeyValueInput (builder-owned, not resolve_control)
    assert _input_for("settings", {"type": "jsonb"})["type"] == "KeyValueInput"


def test_input_for_fk_is_relational_select_with_object_optionsfrom():
    node = _input_for("candidateId", {"type": "uuid", "nullable": False},
                      {"Candidate": {"fields": {"id": {"type": "uuid", "primaryKey": True},
                                                "fullName": {"type": "varchar"}}}})
    assert node["type"] == "Select"
    of = node["props"]["optionsFrom"]
    assert of["source"] == "candidates" and of["value"] == "id"
    assert of["label"] == "fullName"   # best display column, resolved from the target
    assert node["props"].get("validators", {}).get("required") is True


def test_input_for_enum_options_via_resolve_control():
    node = _input_for("stage", {"type": "varchar", "enum_values": ["A", "B"]})
    assert node["type"] == "Select"
    assert [o["value"] for o in node["props"]["options"]] == ["A", "B"]


def test_harvest_workflow_statuses(tmp_path):
    import json, os
    wf = tmp_path / "workflows"; wf.mkdir()
    (wf / "Shortlist.json").write_text(json.dumps({"definition": {"nodes": [
        {"type": "action", "data": {"config": {"actionType": "db_update", "table": "applications", "values": {"status": "Shortlisted"}}}},
        {"type": "action", "data": {"config": {"actionType": "db_update", "table": "applications", "values": {"status": "Rejected"}}}},
        {"type": "exclusive_gateway", "data": {"config": {"expression": "status == 'Hired'"}}},
        {"type": "action", "data": {"config": {"actionType": "db_update", "values": {"recruiterNotes": "{{notes}}"}}}}  # free text + template -> ignored
    ]}}), encoding="utf-8")
    out = harvest_workflow_statuses(str(tmp_path))
    got = out.get("status") or out.get("Status") or []
    assert set(got) == {"Shortlisted", "Rejected", "Hired"}
    assert "recruiterNotes" not in {k.lower() for k in out}  # free-text column not harvested
