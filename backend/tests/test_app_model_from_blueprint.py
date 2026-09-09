"""H-INDEX regression: /app-model derives from the Blueprint when no on-disk
index exists (the blueprint pipeline never writes app-model.json)."""
from services.blueprint_to_editor import app_model_from_blueprint


def _doc():
    return {
        "data": {
            "entities": [
                {"id": "ENTITY-001", "name": "User", "table": "users", "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True, "required": True},
                    {"name": "email", "type": "string", "required": True, "unique": True},
                    {"name": "role", "type": "enum", "required": True,
                     "enumValues": ["OWNER", "VET"]},
                ]},
                {"id": "ENTITY-002", "name": "Pet", "table": "pets", "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True, "required": True},
                    {"name": "ownerId", "type": "uuid", "required": True},
                    {"name": "name", "type": "string"},
                ]},
            ],
            "relationships": [
                {"from": "ENTITY-002", "fromField": "ownerId", "to": "ENTITY-001",
                 "toField": "id", "kind": "many_to_one"},
            ],
        },
        "workflows": [{"id": "FLOW-001", "name": "Add Pet", "status": "ACTIVE"}],
        "businessRules": [{"id": "RULE-001", "name": "R", "status": "ACTIVE"}],
        "pages": [{"id": "PAGE-001", "name": "Home"}],
    }


def test_derives_tables_columns_enums_and_relations(tmp_path):
    m = app_model_from_blueprint(_doc(), "pid", str(tmp_path))
    tables = {t["name"]: t for t in m["database"]["tables"]}
    assert set(tables) == {"users", "pets"}
    # columns + nullability from `required`
    email = next(c for c in tables["users"]["columns"] if c["name"] == "email")
    assert email["nullable"] is False and email.get("unique") is True
    name = next(c for c in tables["pets"]["columns"] if c["name"] == "name")
    assert name["nullable"] is True  # not required → nullable
    # primary key
    assert next(c for c in tables["users"]["columns"] if c["name"] == "id")["primaryKey"] is True
    # foreign key reference: pets.ownerId → users
    owner = next(c for c in tables["pets"]["columns"] if c["name"] == "ownerId")
    assert owner["references"] == {"table": "users", "column": "id"}
    # entity relation edge on pets
    assert any(r["target"] == "users" and r["foreignKey"] == "ownerId"
               for r in tables["pets"]["relations"])
    # enum collected
    assert any(e["values"] == ["OWNER", "VET"] for e in m["database"]["enums"])
    # workflows / rules / pages carried through
    assert len(m["workflows"]) == 1 and len(m["businessRules"]) == 1 and len(m["pages"]) == 1
    assert m["derivedFrom"] == "blueprint"


def test_superseded_entities_dropped(tmp_path):
    doc = _doc()
    doc["data"]["entities"][1]["status"] = "SUPERSEDED"
    m = app_model_from_blueprint(doc, "pid", str(tmp_path))
    assert [t["name"] for t in m["database"]["tables"]] == ["users"]


def test_empty_blueprint_is_safe(tmp_path):
    m = app_model_from_blueprint({}, "pid", str(tmp_path))
    assert m["database"]["tables"] == [] and m["database"]["enums"] == []
