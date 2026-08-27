"""Tests for Spec D Wave 2 — planner-authored `column.semantic` blob
precedence on semantic_field_types.apply_semantic_field_types.

The blob shape is ``{control?, enum_values?, format?}``. Additive: the
existing resolve_control classifier stays intact as the fallback and the
pre-Spec-D precedence for plan `enum_values`/`semantic_type` is preserved.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.semantic_field_types import apply_semantic_field_types


def _write_plan(tmp: Path, entities_dict: dict) -> None:
    # plan_field_lookup.load_plan reads src/contracts/plan.json and expects
    # entities to be dict-shaped {Name: {fields: [...]}}.
    p = tmp / "src" / "contracts" / "plan.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"entities": entities_dict}), encoding="utf-8")


def _write_registry(tmp: Path, entities: dict) -> None:
    (tmp / "registry.json").write_text(
        json.dumps({"entities": entities}), encoding="utf-8"
    )


def _write_schema(tmp: Path, rel_path: str, schema: dict) -> Path:
    p = tmp / "src" / "schemas" / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(schema), encoding="utf-8")
    return p


def _widget_form(field_name: str, control: str = "Input", extra: dict | None = None) -> dict:
    props = {"name": field_name, "label": field_name.title()}
    if extra:
        props.update(extra)
    return {
        "root": {
            "type": "Form",
            "props": {"workflow": "CreateWidget"},
            "children": [{"type": control, "props": props}],
        }
    }


def _read_field(p: Path) -> dict:
    doc = json.loads(p.read_text(encoding="utf-8"))
    return doc["root"]["children"][0]


class TestPlannerSemanticControlWins:
    def test_planner_control_overrides_resolve_control(self, tmp_path):
        # Registry says the column is `text` (would default to Input).
        # Planner blob says control=Textarea — we honor that verbatim.
        _write_registry(tmp_path, {
            "Widget": {"fields": {"colorNote": {"type": "text"}}}
        })
        _write_plan(tmp_path, {
            "Widget": {"fields": [
                {"name": "colorNote", "semantic": {"control": "Textarea"}},
            ]}
        })
        p = _write_schema(tmp_path, "widgets/new.json",
                          _widget_form("colorNote", control="Input"))
        rep = apply_semantic_field_types(str(tmp_path))
        assert rep["retyped"] >= 1
        assert _read_field(p)["type"] == "Textarea"


class TestPlannerSemanticEnumValues:
    def test_semantic_enum_values_materialize_select_options(self, tmp_path):
        # A varchar column with no registry enum_values; planner supplies
        # enum_values inside the semantic blob AND control=Select.
        _write_registry(tmp_path, {
            "Widget": {"fields": {"tier": {"type": "varchar"}}}
        })
        _write_plan(tmp_path, {
            "Widget": {"fields": [
                {"name": "tier", "semantic": {
                    "control": "Select",
                    "enum_values": ["Gold", "Silver", "Bronze"],
                }},
            ]}
        })
        p = _write_schema(tmp_path, "widgets/new.json",
                          _widget_form("tier", control="Input"))
        rep = apply_semantic_field_types(str(tmp_path))
        assert rep["retyped"] >= 1
        node = _read_field(p)
        assert node["type"] == "Select"
        values = [o["value"] for o in node["props"]["options"]]
        assert values == ["Gold", "Silver", "Bronze"]


class TestPlannerSemanticFormat:
    def test_planner_format_prop_passes_through(self, tmp_path):
        # planner control=Input, format="phone" — the format prop should
        # end up on the emitted node.
        _write_registry(tmp_path, {
            "Widget": {"fields": {"contact": {"type": "text"}}}
        })
        _write_plan(tmp_path, {
            "Widget": {"fields": [
                {"name": "contact", "semantic": {
                    "control": "Input", "format": "phone",
                }},
            ]}
        })
        p = _write_schema(tmp_path, "widgets/new.json",
                          _widget_form("contact", control="Textarea"))
        rep = apply_semantic_field_types(str(tmp_path))
        assert rep["retyped"] >= 1
        node = _read_field(p)
        assert node["type"] == "Input"
        assert node["props"].get("format") == "phone"


class TestLegacyPathPreserved:
    def test_no_semantic_blob_uses_resolve_control(self, tmp_path):
        # No semantic blob → resolve_control classifies. `text` + no
        # long-form NAME → Input (see semantic_field_types._decide).
        _write_registry(tmp_path, {
            "Widget": {"fields": {"name": {"type": "text"}}}
        })
        _write_plan(tmp_path, {
            "Widget": {"fields": [{"name": "name"}]}
        })
        p = _write_schema(tmp_path, "widgets/new.json",
                          _widget_form("name", control="Textarea"))
        rep = apply_semantic_field_types(str(tmp_path))
        # Rewritten Textarea→Input by legacy path.
        assert rep["retyped"] >= 1
        assert _read_field(p)["type"] == "Input"


class TestFlagShapeTolerance:
    def test_non_dict_semantic_falls_through(self, tmp_path):
        # `semantic: "widget"` isn't a dict — legacy classifier runs.
        _write_registry(tmp_path, {
            "Widget": {"fields": {"name": {"type": "text"}}}
        })
        _write_plan(tmp_path, {
            "Widget": {"fields": [
                {"name": "name", "semantic": "widget"},
            ]}
        })
        p = _write_schema(tmp_path, "widgets/new.json",
                          _widget_form("name", control="Textarea"))
        apply_semantic_field_types(str(tmp_path))
        # Legacy classifier picked; short 'name' should be Input.
        assert _read_field(p)["type"] == "Input"

    def test_invalid_control_falls_through(self, tmp_path):
        # control="Unicorn" isn't a valid _FIELD_TYPES member — fall through.
        _write_registry(tmp_path, {
            "Widget": {"fields": {"note": {"type": "text"}}}
        })
        _write_plan(tmp_path, {
            "Widget": {"fields": [
                {"name": "note", "semantic": {"control": "Unicorn"}},
            ]}
        })
        p = _write_schema(tmp_path, "widgets/new.json",
                          _widget_form("note", control="Input"))
        apply_semantic_field_types(str(tmp_path))
        # 'note' matches _NAME_TEXT_RE → Textarea by legacy.
        assert _read_field(p)["type"] == "Textarea"
