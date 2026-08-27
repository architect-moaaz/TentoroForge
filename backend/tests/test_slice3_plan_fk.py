"""Slice 3 — plan-declared fk beats convention inference.

When the plan says `fields[].fk: {table, column}`, the FK dropdown source
is that table. No name inference, no relation guessing. The convention path
survives as backward-compat fallback for plans that don't carry fk.
"""
from __future__ import annotations
import json


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def _find(schema, name):
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name") == name:
                return n
            for v in n.values():
                r = walk(v)
                if r: return r
        elif isinstance(n, list):
            for v in n:
                r = walk(v)
                if r: return r
        return None
    return walk(schema)


def test_plan_fk_target_wins_over_convention(tmp_path):
    """Convention would resolve `categoryId` to `Assignee` (missing entity),
    but plan says the FK targets `User` → dropdown points at User."""
    from services.form_scaffold import repair_fk_dropdowns
    from services.plan_field_lookup import _CACHE
    _CACHE.clear()

    _write(tmp_path / "registry.json", {
        "entities": {
            "Task": {"fields": {
                "id":          {"type": "uuid", "primaryKey": True},
                "categoryId":  {"type": "uuid"},
            }},
            "User": {"fields": {
                "id":    {"type": "uuid", "primaryKey": True},
                "email": {"type": "varchar"},
            }},
        },
        "relations": [],  # no relation declared — convention alone would flounder
    })
    _write(tmp_path / "src" / "contracts" / "plan.json", {
        "entities": {
            "Task": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "categoryId", "type": "uuid",
                 "fk": {"table": "User", "column": "id"}},
            ]},
        },
    })
    _write(tmp_path / "src" / "schemas" / "tasks" / "new.json", {
        "route": "/tasks/new",
        "root": {"type": "Form", "props": {"workflow": "CreateTask"}, "children": [
            {"type": "Input", "props": {"name": "categoryId", "label": "Assignee"}},
        ]},
    })

    repair_fk_dropdowns(str(tmp_path))
    schema = json.loads((tmp_path / "src" / "schemas" / "tasks" / "new.json").read_text())
    node = _find(schema, "categoryId")
    assert node["type"] == "Select", (
        "plan-declared fk should upgrade the Input to a Select"
    )
    assert node["props"]["optionsFrom"]["source"] == "users"


def test_plan_silent_falls_through_to_convention(tmp_path):
    """Legacy plans that don't carry fk still work through convention inference."""
    from services.form_scaffold import repair_fk_dropdowns
    from services.plan_field_lookup import _CACHE
    _CACHE.clear()

    _write(tmp_path / "registry.json", {
        "entities": {
            "Task": {"fields": {
                "id":         {"type": "uuid", "primaryKey": True},
                "candidateId": {"type": "uuid"},
            }},
            "Candidate": {"fields": {
                "id":    {"type": "uuid", "primaryKey": True},
                "email": {"type": "varchar"},
            }},
        },
        "relations": [{"from_entity": "Task", "to_entity": "Candidate", "type": "many-to-one"}],
    })
    _write(tmp_path / "src" / "contracts" / "plan.json", {
        "entities": {
            "Task": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "candidateId", "type": "uuid"},   # NO fk declared
            ]},
        },
    })
    _write(tmp_path / "src" / "schemas" / "tasks" / "new.json", {
        "route": "/tasks/new",
        "root": {"type": "Form", "props": {"workflow": "CreateTask"}, "children": [
            {"type": "Input", "props": {"name": "candidateId"}},
        ]},
    })

    repair_fk_dropdowns(str(tmp_path))
    schema = json.loads((tmp_path / "src" / "schemas" / "tasks" / "new.json").read_text())
    node = _find(schema, "candidateId")
    # Convention resolved via relations → Candidate.
    assert node["type"] == "Select"
    assert node["props"]["optionsFrom"]["source"] == "candidates"
