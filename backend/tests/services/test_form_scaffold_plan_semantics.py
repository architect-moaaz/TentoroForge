"""Spec D W2 — form_scaffold.scaffold_forms honours planner-authored
`semantic.control` (via plan_column_semantics) BEFORE running the
name+type ``_decide`` classifier."""
from __future__ import annotations

import json
from pathlib import Path

from services.form_scaffold import scaffold_forms


def _write_registry(tmp: Path, entities: dict) -> None:
    (tmp / "registry.json").write_text(
        json.dumps({"entities": entities}), encoding="utf-8"
    )


def _write_plan(tmp: Path, entities: dict) -> None:
    p = tmp / "src" / "contracts" / "plan.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"entities": entities}), encoding="utf-8")


def _write_empty_form(tmp: Path, entity: str) -> Path:
    p = tmp / "src" / "schemas" / f"{entity.lower()}s" / "new.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "root": {
            "type": "Form",
            "props": {"workflow": f"Create{entity}"},
            "children": [],
        }
    }), encoding="utf-8")
    return p


class TestPlanControlBeatsDecideClassifier:
    def test_planner_textarea_wins_over_input_default(self, tmp_path):
        # `note` on a varchar column: `_decide` would leave it as
        # Input (name doesn't hit _NAME_TEXT_RE). Planner says Textarea
        # via the semantic blob — scaffold_forms must honour it.
        _write_registry(tmp_path, {
            "Widget": {"fields": {"note": {"type": "varchar"}}},
        })
        _write_plan(tmp_path, {"Widget": {"fields": [
            {"name": "note", "semantic": {"control": "Textarea"}},
        ]}})
        p = _write_empty_form(tmp_path, "Widget")

        rep = scaffold_forms(str(tmp_path))
        assert rep["added"] >= 1

        schema = json.loads(p.read_text(encoding="utf-8"))
        # scaffold_forms appends to root.children (Form's container).
        added = [c for c in schema["root"]["children"] if c.get("props", {}).get("name") == "note"]
        assert added, "note field was not scaffolded"
        assert added[0]["type"] == "Textarea"

    def test_planner_select_materializes_enum_values(self, tmp_path):
        # varchar column; planner supplies control=Select + enum_values.
        _write_registry(tmp_path, {
            "Widget": {"fields": {"tier": {"type": "varchar"}}},
        })
        _write_plan(tmp_path, {"Widget": {"fields": [
            {"name": "tier", "semantic": {
                "control": "Select",
                "enum_values": ["Gold", "Silver", "Bronze"],
            }},
        ]}})
        p = _write_empty_form(tmp_path, "Widget")

        scaffold_forms(str(tmp_path))

        schema = json.loads(p.read_text(encoding="utf-8"))
        added = [c for c in schema["root"]["children"]
                 if c.get("props", {}).get("name") == "tier"]
        assert added, "tier field was not scaffolded"
        assert added[0]["type"] == "Select"
        values = [o["value"] for o in added[0]["props"]["options"]]
        assert values == ["Gold", "Silver", "Bronze"]

    def test_no_plan_falls_back_to_decide(self, tmp_path):
        # No plan → legacy _decide classifier fires. `description` name
        # hits _NAME_TEXT_RE → Textarea via the name-fallback path.
        _write_registry(tmp_path, {
            "Widget": {"fields": {"description": {"type": "varchar"}}},
        })
        p = _write_empty_form(tmp_path, "Widget")

        scaffold_forms(str(tmp_path))

        schema = json.loads(p.read_text(encoding="utf-8"))
        added = [c for c in schema["root"]["children"]
                 if c.get("props", {}).get("name") == "description"]
        assert added
        assert added[0]["type"] == "Textarea"
