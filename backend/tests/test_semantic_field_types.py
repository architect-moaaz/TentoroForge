"""Form fields should get the right control: enum → Select, numeric → NumberInput,
date → DatePicker, etc. Options come from the seed plan's arrayElement recipes."""
import json

from services.semantic_field_types import (
    harvest_seed_options,
    harvest_workflow_statuses,
    apply_semantic_field_types,
    _decide,
    _FIELD_TYPES,
    _NAME_FILE_RE,
    _name_tokens,
)


def test_fileupload_is_authoritative_field_type():
    # The re-typer must treat a FileUpload node as authoritative (never downgrade it).
    assert "FileUpload" in _FIELD_TYPES


def test_name_file_re_matches_document_nouns_and_suffixes():
    for n in ("cvUrl", "resumeUrl", "documentUrl", "attachmentUrl", "avatarUrl",
              "photoUrl", "cv", "document", "headshot", "logoFile", "scanKey"):
        assert _NAME_FILE_RE.search(_name_tokens(n)), n


def test_name_file_re_rejects_long_text_and_plain_url_columns():
    for n in ("description", "notes", "summary", "comments", "bio", "content",
              "message", "address", "profileUrl", "websiteUrl"):
        assert not _NAME_FILE_RE.search(_name_tokens(n)), n


def _setup(tmp_path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "seed-plan.json").write_text(json.dumps({
        "field_generators": {
            "equipment": {
                "id": "uuid",
                "name": "faker:commerce:productName",
                "category": "faker:helpers:arrayElement[Camera, Lens, Tripod, Lighting]",
                "dailyRate": "faker:number:float{min:10,max:200}",
                "condition": "faker:helpers:arrayElement[New, Good, Fair]",
            },
        }
    }))
    (tmp_path / "registry.json").write_text(json.dumps({"entities": {
        "Equipment": {"fields": {
            "id": {"type": "uuid"},
            "name": {"type": "varchar"},
            "firstName": {"type": "varchar"},
            "category": {"type": "varchar"},
            "dailyRate": {"type": "numeric"},
            "condition": {"type": "varchar"},
            "notes": {"type": "text"},
            "description": {"type": "text"},
            "quantity": {"type": "integer"},
            "scheduledAt": {"type": "timestamp"},
            "status": {"type": "varchar", "enum_values": ["Available", "Rented", "Maintenance"]},
        }},
    }}))
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    return sdir


def _all_inputs(*names):
    return {"root": {"type": "Form", "props": {}, "children": [
        {"type": "Input", "props": {"name": n, "label": n}} for n in names
    ]}}


def test_harvest_reads_arrayelement_options(tmp_path):
    _setup(tmp_path)
    opts = harvest_seed_options(str(tmp_path))
    assert opts["equipment"]["category"] == ["Camera", "Lens", "Tripod", "Lighting"]
    assert opts["equipment"]["condition"] == ["New", "Good", "Fair"]


def test_decide_rules():
    assert _decide("category", "varchar", ["A", "B"])[0] == "Select"
    assert _decide("dailyRate", "numeric", None)[0] == "NumberInput"
    assert _decide("quantity", "", None)[0] == "NumberInput"
    assert _decide("scheduledAt", "timestamp", None)[0] == "DatePicker"
    assert _decide("isActive", "boolean", None)[0] == "Switch"
    assert _decide("description", "text", None)[0] == "Textarea"
    assert _decide("name", "varchar", None)[0] is None  # plain text stays Input


def test_decide_money_fields_have_no_stepper():
    """Currency-shaped fields → NumberInput with showSteppers False + a $ prefix
    (a +/- unit stepper is nonsensical for money). Covers money by NAME and by
    generic numeric SQL type. Slice 2 note: an EXPLICIT `type: "money"` column
    is separately handled — it lands on the first-class `MoneyInput` (see
    ``test_semantic_field_types_money.py``), so the `balance/money` pair no
    longer belongs here."""
    for name, sql in [("dailyRate", "integer"), ("totalCost", "numeric"),
                      ("amount", "numeric"), ("price", "integer"),
                      ("fee", "")]:
        node, props = _decide(name, sql, None)
        assert node == "NumberInput", (name, sql)
        assert props.get("showSteppers") is False, (name, sql)
        assert props.get("prefix") == "$", (name, sql)
        assert props.get("step") == 0.01, (name, sql)


def test_decide_quantity_fields_keep_stepper():
    """Quantity/count fields keep the stepper (unit increments) — showSteppers is
    never forced False, and the step is 1."""
    for name, sql in [("quantity", ""), ("unitsInStock", "integer"),
                      ("stock", "integer"), ("seatCount", "")]:
        node, props = _decide(name, sql, None)
        assert node == "NumberInput", (name, sql)
        assert props.get("showSteppers") is not False, (name, sql)
        assert props.get("step") == 1, (name, sql)


def test_harvest_status_from_node_labels(tmp_path):
    """Transition targets written as `values:{status:"{{status}}"}` (template) are
    recovered from the state-setting node's label ("Set Returned" -> "Returned"),
    alongside the literal gateway comparison ("Reserved")."""
    wdir = tmp_path / "workflows"
    wdir.mkdir()
    (wdir / "rental.json").write_text(json.dumps({"nodes": [
        {"label": "Set Returned", "actionType": "db_update",
         "config": {"values": {"status": "{{status}}"}}},
        {"label": "Mark as Cancelled", "actionType": "db_update",
         "config": {"values": {"status": "{{status}}"}}},
        {"type": "gateway", "config": {"condition": "status == 'Reserved'"}},
    ]}))
    out = harvest_workflow_statuses(str(tmp_path))
    assert "status" in out
    assert set(out["status"]) >= {"Reserved", "Returned", "Cancelled"}


def test_apply_retypes_equipment_form(tmp_path):
    sdir = _setup(tmp_path)
    (sdir / "equipment.json").write_text(json.dumps(
        _all_inputs("name", "category", "dailyRate", "condition", "notes")))

    res = apply_semantic_field_types(str(tmp_path))
    assert res["retyped"] >= 4

    schema = json.loads((sdir / "equipment.json").read_text())
    by_name = {}
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"):
                by_name[n["props"]["name"]] = n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(schema)

    assert by_name["category"]["type"] == "Select"
    assert {o["value"] for o in by_name["category"]["props"]["options"]} == {
        "Camera", "Lens", "Tripod", "Lighting"}
    assert by_name["dailyRate"]["type"] == "NumberInput"
    assert by_name["dailyRate"]["props"].get("step") == 0.01  # money → cents step
    assert by_name["condition"]["type"] == "Select"
    assert by_name["notes"]["type"] == "Textarea"
    assert by_name["name"]["type"] == "Input"  # unchanged


def test_leaves_fk_optionsfrom_untouched(tmp_path):
    sdir = _setup(tmp_path)
    (sdir / "equipment.json").write_text(json.dumps({"root": {"type": "Form", "children": [
        {"type": "Select", "props": {"name": "ownerId", "label": "Owner",
                                     "optionsFrom": {"source": "owners", "value": "id", "label": "name"}}},
    ]}}))
    apply_semantic_field_types(str(tmp_path))
    schema = json.loads((sdir / "equipment.json").read_text())
    sel = schema["root"]["children"][0]
    assert sel["props"].get("optionsFrom")  # still a relational dropdown
    assert "options" not in sel["props"]


def test_missing_schemas_dir_safe(tmp_path):
    assert apply_semantic_field_types(str(tmp_path)) == {"retyped": 0, "files": 0}


def test_downgrades_optionless_select_to_input_preserving_required(tmp_path):
    # The LLM page agent authored a plain varchar `name` as an EMPTY Select (no options) with
    # a required validator, and `condition`/`notes` similarly. The re-typer must demote the
    # option-less Selects on free-text columns to Input (Textarea for text-named) and KEEP the
    # required flag — while a Select on a column with real enum options stays a Select.
    sdir = _setup(tmp_path)
    (sdir / "equipment_new.json").write_text(json.dumps({"root": {"type": "Form", "props": {}, "children": [
        {"type": "Select", "props": {"name": "name", "label": "Name", "validators": {"required": True}}},
        {"type": "Select", "props": {"name": "notes", "label": "Notes"}},
        {"type": "Select", "props": {"name": "category", "label": "Category"}},  # has seed arrayElement opts
    ]}}))
    apply_semantic_field_types(str(tmp_path))
    kids = json.loads((sdir / "equipment_new.json").read_text())["root"]["children"]
    by = {c["props"]["name"]: c for c in kids}
    assert by["name"]["type"] == "Input"          # option-less Select on varchar -> Input
    assert (by["name"]["props"].get("validators") or {}).get("required") is True  # required preserved
    assert by["notes"]["type"] == "Textarea"      # text-named -> Textarea
    assert by["category"]["type"] == "Select"     # real enum options -> stays Select
    assert by["category"]["props"].get("options")


# --- Authority: control is DERIVED from the column via resolve_control, never the LLM's guess ---

def _form(*nodes):
    return {"root": {"type": "Form", "props": {}, "children": list(nodes)}}


def _apply_single(tmp_path, node):
    """Write a one-field equipment form, apply the pass, return the field node back."""
    sdir = _setup(tmp_path)
    (sdir / "equipment.json").write_text(json.dumps(_form(node)))
    apply_semantic_field_types(str(tmp_path))
    return json.loads((sdir / "equipment.json").read_text())["root"]["children"][0]


def test_empty_select_on_plain_varchar_becomes_input_keeps_required(tmp_path):
    """The g2ter02v bug: an empty Select the LLM emitted on a plain varchar `firstName`
    is DERIVED to a plain Input (its real control), and the required validator survives —
    now impossible by construction because the LLM's control is never consulted."""
    out = _apply_single(tmp_path, {"type": "Select", "props": {
        "name": "firstName", "label": "First Name", "validators": {"required": True}}})
    assert out["type"] == "Input"
    assert (out["props"].get("validators") or {}).get("required") is True


def test_plain_input_on_enum_status_upgrades_to_select_with_options(tmp_path):
    """Upgrade still works: a plain Input on a `status` column with harvested/declared
    enum options becomes a Select carrying those options."""
    out = _apply_single(tmp_path, {"type": "Input", "props": {"name": "status", "label": "Status"}})
    assert out["type"] == "Select"
    assert {o["value"] for o in out["props"]["options"]} == {"Available", "Rented", "Maintenance"}


def test_plain_input_on_integer_becomes_numberinput(tmp_path):
    out = _apply_single(tmp_path, {"type": "Input", "props": {"name": "quantity", "label": "Quantity"}})
    assert out["type"] == "NumberInput"
    assert out["props"].get("step") == 1  # integer -> unit stepper


def test_plain_input_on_timestamp_becomes_datepicker(tmp_path):
    out = _apply_single(tmp_path, {"type": "Input", "props": {"name": "scheduledAt", "label": "Scheduled At"}})
    assert out["type"] == "DatePicker"


def test_text_column_becomes_textarea(tmp_path):
    out = _apply_single(tmp_path, {"type": "Input", "props": {"name": "description", "label": "Description"}})
    assert out["type"] == "Textarea"


def test_relational_select_with_optionsfrom_is_untouched(tmp_path):
    """An existing relational FK Select keeps its control AND its optionsFrom source —
    the binding pass owns it; the control authority does not overwrite it."""
    of = {"source": "owners", "value": "id", "label": "name"}
    out = _apply_single(tmp_path, {"type": "Select", "props": {
        "name": "ownerId", "label": "Owner", "optionsFrom": of}})
    assert out["type"] == "Select"
    assert out["props"].get("optionsFrom") == of
    assert "options" not in out["props"]
