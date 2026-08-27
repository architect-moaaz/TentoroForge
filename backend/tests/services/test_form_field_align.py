from services.form_field_align import align_form_fields

_REG = {"entities": {"Property": {"fields": {
    "id": {"primaryKey": True}, "landlordId": {"nullable": False},
    "propertyType": {"nullable": False}, "totalUnits": {"type": "integer"},
    "address": {}, "createdAt": {}, "deletedAt": {},
}}}}


def test_renames_snake_to_real_column():
    schema = {"root": {"type": "Form", "children": [
        {"type": "Input", "props": {"name": "property_type"}},
        {"type": "Input", "props": {"name": "total_units"}},
        {"type": "Input", "props": {"name": "address"}},
        {"type": "Input", "props": {"name": "has_gym"}},  # invented → left as-is
    ]}}
    out, rep = align_form_fields(schema, "Property", _REG)
    names = [n["props"]["name"] for n in out["root"]["children"]]
    assert "propertyType" in names and "totalUnits" in names and "address" in names
    assert "has_gym" in names  # unmatched left for the runtime to drop
    assert rep["renamed"] == 2


def test_noop_without_entity_or_columns():
    s = {"root": {"type": "Form", "children": []}}
    assert align_form_fields(s, None, _REG)[1]["renamed"] == 0
    assert align_form_fields(s, "Ghost", _REG)[1]["renamed"] == 0


# --- B-5b: completeness backfill covers ALL editable columns, not just NOT-NULL ---

# 8 editable columns (all nullable), + PK / system timestamps / a hidden actor FK.
_B5B_REG = {"entities": {
    "Task": {"fields": {
        "id": {"primaryKey": True},
        "createdAt": {}, "updatedAt": {},
        "ownerId": {},                                 # actor/tenancy FK → hidden, never a field
        "title": {"type": "varchar", "nullable": True},
        "description": {"type": "text", "nullable": True},
        "amount": {"type": "integer", "nullable": True},
        "startDate": {"type": "date", "nullable": True},
        "isActive": {"type": "boolean", "nullable": True},
        "config": {"type": "jsonb", "nullable": True},
        "candidateId": {"type": "varchar", "nullable": True},   # domain FK → Select
        "status": {"type": "varchar", "nullable": True, "enum_values": ["open", "done"]},
    }},
    "Candidate": {"fields": {"id": {"primaryKey": True}, "fullName": {}}},
}}


def _field_nodes(schema):
    from services.form_field_align import _INPUT_TYPES
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") in _INPUT_TYPES and (n.get("props") or {}).get("name"):
                out.append(n)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(schema.get("root") or schema)
    return out


def test_backfill_covers_all_editable_columns_not_just_required():
    # LLM authored only 3 of 8 editable columns; every column is nullable.
    schema = {"root": {"type": "Form", "props": {"workflow": "CreateTask"}, "children": [
        {"type": "Stack", "children": [
            {"type": "Input", "props": {"name": "title"}},
            {"type": "NumberInput", "props": {"name": "amount"}},
            {"type": "Select", "props": {"name": "status"}},
        ]},
    ]}}
    out, rep = align_form_fields(schema, "Task", _B5B_REG)

    by_name = {n["props"]["name"]: n["type"] for n in _field_nodes(out)}
    # the 5 missing editable columns are appended
    assert set(rep["added"]) == {"description", "startDate", "isActive", "config", "candidateId"}
    for col in ("title", "description", "amount", "startDate", "isActive",
                "config", "candidateId", "status"):
        assert col in by_name
    # correct control types from the shared authority
    assert by_name["config"] == "KeyValueInput"       # jsonb → editable map
    assert by_name["isActive"] == "Switch"            # boolean
    assert by_name["startDate"] == "DatePicker"       # date
    assert by_name["candidateId"] == "Select"         # domain FK
    # PK / system timestamps / hidden actor FK are NEVER added
    for col in ("id", "createdAt", "updatedAt", "ownerId"):
        assert col not in by_name

    # idempotent: a second pass adds nothing
    out2, rep2 = align_form_fields(out, "Task", _B5B_REG)
    assert rep2["added"] == []
    assert len(_field_nodes(out2)) == len(_field_nodes(out))
