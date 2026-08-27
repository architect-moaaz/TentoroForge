"""A hidden input is not a free-text input.

Why this test exists
--------------------
The ``type_incompatible`` rule catches a real crash: a user typing prose into a
control that feeds a uuid column. Measured across six shipped apps it found 15
hits — and 8 of them were this, on edit forms:

    {"name": "id", "type": "hidden", "defaultValue": "{{session.id}}"}

which is the CORRECT shape. The record's own key is supplied by the route and
carried hidden; there is no way to type into it. The rule read the NODE type
(``Input``) and never ``props.type``, so a machine-filled hidden field looked
like free text.

This is worth a test rather than a one-line patch because the gate is being
promoted to blocking. A false positive in a blocking gate fails builds on apps
that are correct — strictly worse than the bug it was written to catch.

The fixture mirrors the real app shape exactly, which is not obvious:
schema lives in ``src/db/schema/*.ts`` (a DIRECTORY), workflows in
``<root>/workflows``, and a workflow's columns come from
``definition.nodes[].data.config.values``. Getting any of those wrong makes the
rule silently not fire, and the test passes for the wrong reason.
"""

import json
from pathlib import Path

from services.binding_validator import validate_bindings

HIDDEN_PK = {"type": "Input", "props": {
    "name": "id", "type": "hidden", "defaultValue": "{{session.id}}"}}
VISIBLE_PK = {"type": "Input", "props": {"name": "id", "label": "Id"}}
VISIBLE_TITLE = {"type": "Input", "props": {"name": "title", "label": "Title"}}


def _app(tmp_path: Path, *fields: dict) -> str:
    root = tmp_path / "app"
    (root / "src" / "db" / "schema").mkdir(parents=True)
    (root / "src" / "schemas" / "sessions" / "[id]").mkdir(parents=True)
    (root / "workflows").mkdir(parents=True)

    (root / "src" / "db" / "schema" / "sessions.ts").write_text(
        'export const sessions = pgTable("sessions", {\n'
        '  id: uuid("id").primaryKey().defaultRandom(),\n'
        '  title: varchar("title", { length: 255 }),\n'
        "});\n", encoding="utf-8")

    (root / "workflows" / "UpdateSession.json").write_text(json.dumps({
        "id": "update-session", "name": "UpdateSession",
        "definition": {
            "trigger": {"type": "manual"},
            "nodes": [{"id": "db_update", "type": "action", "data": {"config": {
                "actionType": "db_update", "table": "sessions",
                "values": {"id": "{{id}}", "title": "{{title}}"}}}}],
            "edges": [],
        },
    }), encoding="utf-8")

    (root / "src" / "schemas" / "sessions" / "[id]" / "edit.json").write_text(
        json.dumps({
            "schemaVersion": "2", "id": "session-edit",
            "route": "/sessions/[id]/edit", "layout": "main",
            "dataSources": [{"name": "session", "entity": "Session", "op": "get"}],
            "root": {"type": "Stack", "props": {}, "children": [
                {"type": "Form", "props": {"workflow": "UpdateSession"},
                 "children": list(fields)},
            ]},
        }), encoding="utf-8")
    return str(root)


def _type_errors(res: dict) -> list:
    return [e for e in res["errors"] if e["kind"] == "type_incompatible"]


def test_the_rule_fires_at_all(tmp_path):
    """Guard the fixture itself. Every earlier attempt at this test passed
    because the rule never ran — wrong schema path, wrong workflow shape. A
    green suite that proves nothing is the failure mode worth pinning."""
    errs = _type_errors(validate_bindings(_app(tmp_path, VISIBLE_PK)))
    assert len(errs) == 1 and errs[0]["ref"] == "id", errs


def test_a_hidden_route_supplied_key_is_not_a_finding(tmp_path):
    """The 8-of-15 false positive."""
    assert _type_errors(validate_bindings(_app(tmp_path, HIDDEN_PK))) == []


def test_a_visible_field_beside_a_hidden_one_is_unaffected(tmp_path):
    """Exempting hidden must not exempt its siblings."""
    res = validate_bindings(_app(tmp_path, HIDDEN_PK, VISIBLE_TITLE))
    assert _type_errors(res) == []  # title is varchar — never in scope


def test_hidden_is_matched_case_insensitively(tmp_path):
    field = {"type": "Input", "props": {"name": "id", "type": "Hidden"}}
    assert _type_errors(validate_bindings(_app(tmp_path, field))) == []
