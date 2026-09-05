# backend/tests/services/test_crud_workflow_generator.py
import json
from pathlib import Path

from services.crud_workflow_generator import build_crud_workflow, generate_crud_workflows

_FIELDS = [
    {"name": "id", "type": "uuid"},
    {"name": "title", "type": "varchar"},
    {"name": "status", "type": "varchar"},
    {"name": "createdAt", "type": "timestamp"},
    {"name": "updatedAt", "type": "timestamp"},
]


def test_create_workflow_inserts_writable_fields():
    wf = build_crud_workflow("Task", "tasks", _FIELDS, "create")
    assert wf["name"] == "CreateTask"
    nodes = wf["definition"]["nodes"]
    action = next(n for n in nodes if n["type"] == "action")
    cfg = action["data"]["config"]
    assert cfg["actionType"] == "db_insert"
    assert cfg["table"] == "tasks"
    # writable fields only (no id / timestamps)
    assert set(cfg["values"].keys()) == {"title", "status"}
    assert cfg["values"]["title"] == "{{title}}"
    # trigger -> action -> end, fully connected
    assert {n["type"] for n in nodes} == {"trigger", "action", "end"}
    assert len(wf["definition"]["edges"]) == 2
    # process variables cover the writable fields
    assert {p["name"] for p in wf["processVariables"]} == {"title", "status"}


def test_update_workflow_sets_where_id_and_values():
    wf = build_crud_workflow("Task", "tasks", _FIELDS, "update")
    assert wf["name"] == "UpdateTask"
    cfg = next(n for n in wf["definition"]["nodes"] if n["type"] == "action")["data"]["config"]
    assert cfg["actionType"] == "db_update"
    assert cfg["where"] == {"id": "{{id}}"}
    assert set(cfg["values"].keys()) == {"title", "status"}
    assert {p["name"] for p in wf["processVariables"]} == {"id", "title", "status"}


def test_delete_workflow_where_id_only():
    wf = build_crud_workflow("Task", "tasks", _FIELDS, "delete")
    assert wf["name"] == "DeleteTask"
    cfg = next(n for n in wf["definition"]["nodes"] if n["type"] == "action")["data"]["config"]
    assert cfg["actionType"] == "db_delete"
    assert cfg["where"] == {"id": "{{id}}"}
    assert "values" not in cfg
    assert {p["name"] for p in wf["processVariables"]} == {"id"}


def _plan():
    return {"entities": {
        "Task": {"table": "tasks", "fields": [
            {"name": "id", "type": "uuid"}, {"name": "title", "type": "varchar"}]},
        "Tag": {"fields": [{"name": "id"}, {"name": "label"}]},  # no table -> derive
    }}


def test_generate_writes_three_per_entity(tmp_path):
    created = generate_crud_workflows(_plan(), str(tmp_path))
    files = {p.name for p in (tmp_path / "workflows").glob("*.json")}
    assert "CreateTask.json" in files and "UpdateTask.json" in files and "DeleteTask.json" in files
    assert "CreateTag.json" in files  # table derived as "tags"
    cfg = json.loads((tmp_path / "workflows" / "CreateTag.json").read_text())
    table = next(n for n in cfg["definition"]["nodes"] if n["type"] == "action")["data"]["config"]["table"]
    assert table == "tags"
    assert "CreateTask" in created


def test_generate_does_not_overwrite_existing_nonempty(tmp_path):
    wdir = tmp_path / "workflows"; wdir.mkdir()
    existing = {"id": "create-task", "name": "CreateTask",
                "definition": {"nodes": [{"id": "x", "type": "action"}], "edges": []}}
    (wdir / "CreateTask.json").write_text(json.dumps(existing))
    generate_crud_workflows(_plan(), str(tmp_path))
    # untouched (still the 1-node hand version)
    assert json.loads((wdir / "CreateTask.json").read_text())["definition"]["nodes"][0]["id"] == "x"


def test_generate_sources_columns_from_real_drizzle_schema(tmp_path):
    # The plan's User entity is incomplete (no password), but the generated
    # Drizzle schema has email + password as NOT NULL columns. CRUD generation
    # must source insert columns from the real schema so inserts don't violate
    # NOT NULL — and still exclude id (PK) and createdAt (default).
    schema_dir = tmp_path / "src" / "db" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "users.ts").write_text(
        'export const users = pgTable("users", {\n'
        '  id: uuid("id").primaryKey().defaultRandom(),\n'
        '  email: text("email").notNull(),\n'
        '  password: text("password").notNull(),\n'
        '  createdAt: timestamp("created_at").defaultNow()\n'
        "});\n"
    )
    plan = {"entities": {"User": {"table": "users", "fields": [
        {"name": "id", "type": "uuid"}, {"name": "email", "type": "text"}]}}}
    generate_crud_workflows(plan, str(tmp_path))
    cfg = json.loads((tmp_path / "workflows" / "CreateUser.json").read_text())
    values = next(
        n for n in cfg["definition"]["nodes"] if n["type"] == "action"
    )["data"]["config"]["values"]
    assert "password" in values  # real NOT NULL col missing from plan
    assert "email" in values
    assert "id" not in values  # primary key
    assert "createdAt" not in values and "created_at" not in values  # has default


def test_workflow_definition_has_trigger_for_runtime_engine():
    # The runtime engine reads workflow.definition.trigger.inputMapping; without
    # a definition.trigger it crashes at the trigger node. Every CRUD workflow
    # must carry one.
    for op in ("create", "update", "delete"):
        wf = build_crud_workflow("Task", "tasks", _FIELDS, op)
        assert "trigger" in wf["definition"], op
        assert isinstance(wf["definition"]["trigger"], dict)


def test_parse_handles_varchar_length_option_nested_braces(tmp_path):
    # Columns like varchar("x", { length: 255 }) contain a nested {...} — the
    # parser must NOT truncate the table body at that first inner brace.
    from services.crud_workflow_generator import _parse_schema_columns
    sd = tmp_path / "src" / "db" / "schema"; sd.mkdir(parents=True)
    (sd / "user.ts").write_text(
        'export const users = pgTable("users", {\n'
        '  id: uuid("id").primaryKey().defaultRandom(),\n'
        '  email: varchar("email", { length: 255 }).notNull().unique(),\n'
        '  password: text("password").notNull(),\n'
        '  name: varchar("name", { length: 255 }),\n'
        '});\n')
    cols = {c["name"] for c in _parse_schema_columns(str(tmp_path)).get("users", [])}
    assert {"id", "email", "password", "name"} <= cols   # password not lost


def test_delete_workflow_cascades_child_tables(tmp_path):
    """Delete<Entity> must clear FK-dependent child rows BEFORE the parent
    delete (register: dxlc5m31 Discard Scan died on the price_results FK),
    and every ref must use the canonical {{var}} form."""
    from services.crud_workflow_generator import (
        build_crud_workflow, parse_child_references,
    )

    schema_dir = tmp_path / "src" / "db" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "scan-sessions.ts").write_text(
        'import { pgTable, uuid } from "drizzle-orm/pg-core";\n'
        'export const scanSessions = pgTable("scan_sessions", {\n'
        '  id: uuid("id").primaryKey().defaultRandom(),\n'
        '});\n'
    )
    (schema_dir / "price-results.ts").write_text(
        'import { pgTable, uuid } from "drizzle-orm/pg-core";\n'
        'import { scanSessions } from "./scan-sessions";\n'
        'export const priceResults = pgTable("price_results", {\n'
        '  id: uuid("id").primaryKey().defaultRandom(),\n'
        '  scanSessionId: uuid("scan_session_id").references(() => scanSessions.id),\n'
        '});\n'
    )

    refs = parse_child_references(str(tmp_path))
    assert refs == {"scan_sessions": [{"table": "price_results", "fk": "scanSessionId"}]}

    wf = build_crud_workflow(
        "ScanSession", "scan_sessions", [], "delete", pk="id",
        children=refs["scan_sessions"],
    )
    nodes = wf["definition"]["nodes"]
    ids = [n["id"] for n in nodes]
    # cascade node sits between trigger and the parent delete
    assert ids[0] == "trigger" and ids[-1] == "end"
    cascade = next(n for n in nodes if n["id"].startswith("cascade_"))
    cfg = cascade["data"]["config"]
    assert cfg == {"actionType": "db_delete", "table": "price_results",
                   "where": {"scanSessionId": "{{id}}"}, "continueOnError": True,
                   "nodeType": "action"}
    assert ids.index(cascade["id"]) < ids.index("db_delete")
    # edges form one linear chain covering every node
    edges = wf["definition"]["edges"]
    chain = [e["source"] for e in edges] + [edges[-1]["target"]]
    assert chain == ids
    # parent delete uses the canonical binding form
    main = next(n for n in nodes if n["id"] == "db_delete")
    assert main["data"]["config"]["where"] == {"id": "{{id}}"}


def test_nodes_carry_the_editor_type_and_stack_top_to_bottom():
    wf = build_crud_workflow("Task", "tasks", _FIELDS, "delete", pk="id",
                             children=[{"table": "comments", "fk": "task_id"}])
    nodes = wf["definition"]["nodes"]
    for n in nodes:
        assert n["data"]["nodeType"] == n["type"], n
    assert [n["id"] for n in nodes] == ["trigger", "cascade_0_comments", "db_delete", "end"]
    assert {n["position"]["x"] for n in nodes} == {250}
    assert [n["position"]["y"] for n in nodes] == [0, 120, 240, 360]
