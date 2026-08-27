"""Slice 2 — plan-declared semantic_type is the authority for control choice.

Kills Bug 1: the "Based At (Airport/City)" column got a DatePicker because
the field name tripped the date heuristic. When the plan declares the field
is a `city`/`place`/`text`, the heuristic is bypassed and the field ships
as a plain Input.
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


def test_plan_city_beats_date_heuristic(tmp_path):
    """A field name of 'basedAt' would trip _NAME_DATE_RE and become a
    DatePicker. When the plan tags it `semantic_type: "city"`, the plan
    wins and the field ships as a plain Input."""
    from services.semantic_field_types import apply_semantic_field_types
    from services.plan_field_lookup import _CACHE
    _CACHE.clear()

    # Registry says the column is varchar (untyped enough for the heuristic
    # to normally win).
    _write(tmp_path / "registry.json", {
        "entities": {
            "Role": {"fields": {
                "id":      {"type": "uuid", "primaryKey": True},
                "basedAt": {"type": "varchar"},
            }},
        },
    })
    _write(tmp_path / "src" / "contracts" / "plan.json", {
        "entities": {
            "Role": {"fields": [
                {"name": "id",      "type": "uuid", "primaryKey": True},
                {"name": "basedAt", "type": "varchar", "semantic_type": "city"},
            ]},
        },
    })
    _write(tmp_path / "src" / "schemas" / "roles" / "new.json", {
        "route": "/roles/new",
        "root": {"type": "Form", "props": {"workflow": "CreateRole"}, "children": [
            {"type": "Input", "props": {"name": "basedAt", "label": "Based At"}},
        ]},
    })

    apply_semantic_field_types(str(tmp_path))

    schema = json.loads((tmp_path / "src" / "schemas" / "roles" / "new.json").read_text())
    node = _find(schema, "basedAt")
    assert node["type"] == "Input", (
        f"expected plan 'semantic_type=city' to force Input; got {node['type']}. "
        "Bug 1 regression."
    )


def test_plan_semantic_ignored_on_real_date_column(tmp_path):
    """Type authority: even if the plan says `semantic_type=city`, a real
    `date` column should still render as DatePicker — the plan tag is only
    honored when compatible with the SQL type."""
    from services.semantic_field_types import apply_semantic_field_types
    from services.plan_field_lookup import _CACHE
    _CACHE.clear()

    _write(tmp_path / "registry.json", {
        "entities": {
            "Role": {"fields": {
                "id":                {"type": "uuid", "primaryKey": True},
                "applicationClosing": {"type": "date"},
            }},
        },
    })
    _write(tmp_path / "src" / "contracts" / "plan.json", {
        "entities": {
            "Role": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "applicationClosing", "type": "date", "semantic_type": "city"},
            ]},
        },
    })
    _write(tmp_path / "src" / "schemas" / "roles" / "new.json", {
        "route": "/roles/new",
        "root": {"type": "Form", "props": {"workflow": "CreateRole"}, "children": [
            {"type": "Input", "props": {"name": "applicationClosing", "label": "Closing"}},
        ]},
    })

    apply_semantic_field_types(str(tmp_path))

    schema = json.loads((tmp_path / "src" / "schemas" / "roles" / "new.json").read_text())
    node = _find(schema, "applicationClosing")
    assert node["type"] == "DatePicker"


def test_plan_silent_falls_through_to_llm_semanticType(tmp_path):
    """Backward compat: when the plan is silent, the LLM's authored
    `semanticType` prop still wins (legacy path preserved).

    Uses an `image` semantic — the current pipeline maps that to FileUpload,
    so the control CHANGES from Input to FileUpload, proving the semantic
    hint reached resolve_control (unlike an `email` hint on a plain Input
    which would keep the control the same and short-circuit the merge)."""
    from services.semantic_field_types import apply_semantic_field_types
    from services.plan_field_lookup import _CACHE
    _CACHE.clear()

    _write(tmp_path / "registry.json", {
        "entities": {
            "User": {"fields": {
                "id":        {"type": "uuid", "primaryKey": True},
                "avatarUrl": {"type": "varchar"},
            }},
        },
    })
    _write(tmp_path / "src" / "contracts" / "plan.json", {
        "entities": {
            "User": {"fields": [
                {"name": "id",        "type": "uuid", "primaryKey": True},
                {"name": "avatarUrl", "type": "varchar"},   # no semantic_type
            ]},
        },
    })
    _write(tmp_path / "src" / "schemas" / "users" / "new.json", {
        "route": "/users/new",
        "root": {"type": "Form", "props": {"workflow": "CreateUser"}, "children": [
            {"type": "Input", "props": {"name": "avatarUrl", "semanticType": "image"}},
        ]},
    })

    apply_semantic_field_types(str(tmp_path))

    schema = json.loads((tmp_path / "src" / "schemas" / "users" / "new.json").read_text())
    node = _find(schema, "avatarUrl")
    # The LLM's semanticType=image reached resolve_control and forced FileUpload —
    # the plan was silent, so legacy behavior preserved.
    assert node["type"] == "FileUpload"
