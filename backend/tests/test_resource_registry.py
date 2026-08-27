from services.resource_registry import build_canonical_registry, write_registry


def _plan():
    return {
        "data_models": [
            {"name": "Equipment", "table": "equipment",
             "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "name", "type": "varchar", "nullable": False},
                        {"name": "status", "type": "varchar", "enum_values": ["Active", "Retired"]}]},
            {"name": "MaintenanceLog",
             "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "equipmentId", "type": "uuid", "nullable": False}]},
        ],
        "relations": [{"from": "MaintenanceLog", "to": "Equipment", "type": "many-to-one", "foreignKey": "equipmentId"}],
        "pages": [{"route": "equipment", "actions": [
            {"label": "Add Equipment", "workflow": "CreateEquipment", "kind": "page_action"}]}],
        "workflows": [{"id": "CreateEquipment"}],
    }


def test_entity_name_family_and_hint():
    r = build_canonical_registry(_plan())
    eq = r["entities"]["Equipment"]
    assert eq["id"] == "equipment"
    assert eq["table"] == "equipment"             # planner hint honored, NOT "equipments"
    assert eq["slug"] and eq["schemaFile"].endswith(".ts")
    assert any(c["name"] == "status" and c["enum"] == ["Active", "Retired"] for c in eq["columns"])


def test_fk_resolves_to_entity_id():
    r = build_canonical_registry(_plan())
    ml = r["entities"]["MaintenanceLog"]
    fk = next(f for f in ml["fks"] if f["column"] == "equipmentId")
    assert fk["targetEntityId"] == "equipment"


def test_relationship_by_id():
    r = build_canonical_registry(_plan())
    rel = r["relationships"][0]
    assert rel["from"] == "maintenance-log" and rel["to"] == "equipment"


def test_interaction_resolves_workflow_and_target_entity():
    r = build_canonical_registry(_plan())
    it = next(i for i in r["interactions"] if i["label"] == "Add Equipment")
    assert it["workflowId"] == "CreateEquipment"
    assert it["targetEntityId"] == "equipment"       # inferred from workflow/page → entity
    assert it["sourcePage"] == "equipment"


def test_legacy_dict_entities_normalized():
    plan = {"entities": {"Equipment": {"table": "equipment", "fields": [{"name": "id", "type": "uuid"}]}}}
    r = build_canonical_registry(plan)
    assert r["entities"]["Equipment"]["table"] == "equipment"


def test_write_registry_round_trips_and_is_deterministic(tmp_path):
    import json
    reg = build_canonical_registry(_plan())
    out = str(tmp_path / "app")

    path = write_registry(reg, out)
    assert path.endswith("contracts/resource-registry.json")
    import os
    assert os.path.exists(path)

    # round-trips: reloading yields the same registry
    with open(path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == reg

    # deterministic: writing again is byte-identical
    first = open(path, "rb").read()
    write_registry(reg, out)
    second = open(path, "rb").read()
    assert first == second


def test_deterministic_and_reserved_users():
    r1 = build_canonical_registry(_plan())
    r2 = build_canonical_registry(_plan())
    import json
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    # a User entity maps to reserved users table (auth owns it) — still in registry, table "users"
    plan = {"data_models": [{"name": "User", "fields": [{"name": "id", "type": "uuid"}]}]}
    r = build_canonical_registry(plan)
    assert r["entities"]["User"]["table"] == "users"


def _rbac_plan():
    """ATS-shaped plan AFTER the C-1 planner normalizer: roles + a User entity
    mapped to reserved users + an actor FK linked to User via relations."""
    return {
        "access_control": {
            "roles": ["Recruiter", "HiringManager", "Assessor"],
            "rules": ["Assessor: score assigned assessments"],
        },
        "data_models": [
            {"name": "Assessment",
             "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "score", "type": "integer"},
                        {"name": "assignedAssessorId", "type": "uuid"}]},
            {"name": "User", "table": "users",
             "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "name", "type": "varchar"},
                        {"name": "email", "type": "varchar", "nullable": False},
                        {"name": "role", "type": "varchar",
                         "enum_values": ["Recruiter", "HiringManager", "Assessor"]}]},
        ],
        "relations": [
            {"from": "Assessment", "to": "User", "type": "many-to-one",
             "foreignKey": "assignedAssessorId"},
        ],
    }


def test_registry_carries_roles():
    r = build_canonical_registry(_rbac_plan())
    assert r["roles"] == ["Recruiter", "HiringManager", "Assessor"]


def test_registry_has_access_model():
    r = build_canonical_registry(_rbac_plan())
    am = r["accessModel"]
    assert am["roles"] == ["Recruiter", "HiringManager", "Assessor"]
    assert am.get("userEntityId") == "user"


def test_registry_has_user_entity():
    r = build_canonical_registry(_rbac_plan())
    user = r["entities"]["User"]
    assert user["table"] == "users"


def test_assessor_fk_resolves_to_user():
    r = build_canonical_registry(_rbac_plan())
    assessment = r["entities"]["Assessment"]
    col = next(c for c in assessment["columns"] if c["name"] == "assignedAssessorId")
    assert col["fk"] == "user"


def test_user_entity_synthesized_when_absent_but_roles_present():
    """Even if the plan has roles but no explicit User data_model, the registry
    ensures a User entity (table users) exists so actor FKs can resolve."""
    plan = {
        "access_control": {"roles": ["Admin", "Member"]},
        "data_models": [
            {"name": "Note", "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]},
        ],
    }
    r = build_canonical_registry(plan)
    assert "User" in r["entities"]
    assert r["entities"]["User"]["table"] == "users"
    assert r["roles"] == ["Admin", "Member"]


def test_no_roles_no_user_injection():
    """A non-RBAC app (no roles, no actor FKs, no User model) is not polluted with
    a synthetic User entity."""
    r = build_canonical_registry(_plan())
    assert "User" not in r["entities"]
    assert r["roles"] == []
