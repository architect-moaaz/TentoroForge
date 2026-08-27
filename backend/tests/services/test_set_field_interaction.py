"""Tests for set_field_interaction — the resolver+writer used by both
Smith and the editor's Interactions panel."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.set_field_interaction import set_field_interaction


# ── Fixtures ──────────────────────────────────────────────────────────────


def _make_app(tmp_path: Path) -> Path:
    """Create a minimal generated-app structure with a form schema."""
    root = tmp_path / "app"
    (root / "src" / "schemas" / "employees").mkdir(parents=True)

    # A form with the fields we'll test against
    new_schema = {
        "schemaVersion": "2",
        "id": "employees-new",
        "route": "/employees/new",
        "root": {
            "type": "Stack",
            "children": [
                {
                    "type": "Form",
                    "fields": [
                        {"name": "basicSalary", "kind": "number", "label": "Basic Salary"},
                        {"name": "hra", "kind": "number", "label": "HRA"},
                        {"name": "da", "kind": "number", "label": "DA"},
                        {"name": "net", "kind": "number", "label": "Net"},
                        {"name": "country", "kind": "select", "label": "Country"},
                        {"name": "state", "kind": "select", "label": "State"},
                    ],
                }
            ],
        },
    }
    (root / "src" / "schemas" / "employees" / "new.json").write_text(json.dumps(new_schema, indent=2))

    # A simple plan.json for mirror testing
    plan = {
        "pages": [
            {
                "id": "employees-new",
                "route": "/employees/new",
                "fields": [
                    {"name": "basicSalary"},
                    {"name": "hra"},
                    {"name": "da"},
                    {"name": "net"},
                    {"name": "country"},
                    {"name": "state"},
                ],
            }
        ]
    }
    (root / "plan.json").write_text(json.dumps(plan, indent=2))
    return root


# ── Happy paths ───────────────────────────────────────────────────────────


class TestHappy:
    def test_merge_computed_writes_schema(self, tmp_path):
        root = _make_app(tmp_path)
        r = set_field_interaction(
            str(root),
            page="employees/new",
            field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
        )
        assert r["applied"], r
        assert r["changed"]

        # Verify on disk
        data = json.loads((root / "src/schemas/employees/new.json").read_text())
        fields = data["root"]["children"][0]["fields"]
        hra = next(f for f in fields if f["name"] == "hra")
        assert hra["interaction"]["computed"]["formula"] == "basicSalary * 0.4"
        assert hra["interaction"]["computed"]["readOnly"] is True  # default
        assert hra["interaction"]["dependsOn"] == ["basicSalary"]

    def test_merge_cascade_dropdown(self, tmp_path):
        root = _make_app(tmp_path)
        r = set_field_interaction(
            str(root),
            page="employees/new",
            field="state",
            interaction={
                "optionsFrom": {
                    "source": "states",
                    "value": "id",
                    "label": "name",
                    "filter": {"countryId": "{{country}}"},
                }
            },
        )
        # No registry → resource checks skipped, should succeed
        assert r["applied"], r
        data = json.loads((root / "src/schemas/employees/new.json").read_text())
        state = next(
            f for f in data["root"]["children"][0]["fields"] if f["name"] == "state"
        )
        assert state["interaction"]["dependsOn"] == ["country"]

    def test_path_forms_accepted(self, tmp_path):
        """Same schema, three ways to name it."""
        root = _make_app(tmp_path)
        for page in [
            "employees/new",
            "/employees/new",
            "src/schemas/employees/new.json",
        ]:
            r = set_field_interaction(
                str(root),
                page=page,
                field="hra",
                interaction={"computed": {"formula": "basicSalary * 0.4"}},
                mode="replace",
            )
            assert r["applied"], f"page={page}: {r}"


class TestModes:
    def test_replace_wipes_prior(self, tmp_path):
        root = _make_app(tmp_path)
        # Seed an existing interaction
        set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.5"}},
        )
        # Replace with a different formula
        r = set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
            mode="replace",
        )
        assert r["applied"], r
        data = json.loads((root / "src/schemas/employees/new.json").read_text())
        hra = next(
            f for f in data["root"]["children"][0]["fields"] if f["name"] == "hra"
        )
        assert hra["interaction"]["computed"]["formula"] == "basicSalary * 0.4"

    def test_merge_unions_top_level_keys(self, tmp_path):
        root = _make_app(tmp_path)
        # First: computed only
        set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
        )
        # Then: add dependsOn without touching computed
        r = set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"dependsOn": ["basicSalary", "da"]},
            mode="merge",
        )
        assert r["applied"], r
        data = json.loads((root / "src/schemas/employees/new.json").read_text())
        hra = next(
            f for f in data["root"]["children"][0]["fields"] if f["name"] == "hra"
        )
        assert hra["interaction"]["computed"]["formula"] == "basicSalary * 0.4"
        assert set(hra["interaction"]["dependsOn"]) == {"basicSalary", "da"}

    def test_remove_deletes_interaction(self, tmp_path):
        root = _make_app(tmp_path)
        set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
        )
        r = set_field_interaction(
            str(root), page="employees/new", field="hra", mode="remove",
        )
        assert r["applied"], r
        data = json.loads((root / "src/schemas/employees/new.json").read_text())
        hra = next(
            f for f in data["root"]["children"][0]["fields"] if f["name"] == "hra"
        )
        assert "interaction" not in hra

    def test_remove_when_absent_is_noop(self, tmp_path):
        root = _make_app(tmp_path)
        r = set_field_interaction(
            str(root), page="employees/new", field="hra", mode="remove",
        )
        assert r["applied"]
        assert not r["changed"]

    def test_merge_none_removes_subkey(self, tmp_path):
        root = _make_app(tmp_path)
        set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
        )
        r = set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": None},  # explicit drop
            mode="merge",
        )
        assert r["applied"], r
        data = json.loads((root / "src/schemas/employees/new.json").read_text())
        hra = next(
            f for f in data["root"]["children"][0]["fields"] if f["name"] == "hra"
        )
        assert "computed" not in hra.get("interaction", {})


class TestErrors:
    def test_unknown_page(self, tmp_path):
        root = _make_app(tmp_path)
        r = set_field_interaction(
            str(root), page="no/such/page", field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
        )
        assert not r["applied"]
        assert "could not locate" in r["reason"]

    def test_unknown_field_suggests(self, tmp_path):
        root = _make_app(tmp_path)
        r = set_field_interaction(
            str(root), page="employees/new", field="hras",  # not a real field
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
        )
        assert not r["applied"]
        assert "field 'hras' not found" in r["reason"]
        # Should list available fields
        assert "basicSalary" in r["reason"]

    def test_bad_formula_surfaces_validator_error(self, tmp_path):
        root = _make_app(tmp_path)
        r = set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": {"formula": "basicSalery * 0.4"}},  # typo
        )
        assert not r["applied"]
        assert r["errors"]
        joined = " ".join(r["errors"])
        assert "basicSalary" in joined  # suggestion surfaced

    def test_unknown_mode(self, tmp_path):
        root = _make_app(tmp_path)
        r = set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={}, mode="destroy",
        )
        assert not r["applied"]
        assert "unknown mode" in r["reason"]

    def test_non_dict_interaction_in_merge(self, tmp_path):
        root = _make_app(tmp_path)
        r = set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction="not a dict",  # type: ignore[arg-type]
            mode="merge",
        )
        assert not r["applied"]

    def test_bad_output_dir(self, tmp_path):
        r = set_field_interaction(
            str(tmp_path / "nope"), page="x", field="y",
            interaction={"computed": {"formula": "1+1"}},
        )
        assert not r["applied"]
        assert "does not exist" in r["reason"]


class TestPlanMirror:
    def test_writes_to_plan_json(self, tmp_path):
        root = _make_app(tmp_path)
        r = set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
        )
        assert r["applied"]
        # plan.json should be in edited_paths
        assert any("plan.json" in p for p in r["edited_paths"])
        # Interaction is mirrored
        plan = json.loads((root / "plan.json").read_text())
        hra_in_plan = next(
            f for f in plan["pages"][0]["fields"] if f["name"] == "hra"
        )
        assert hra_in_plan["interaction"]["computed"]["formula"] == "basicSalary * 0.4"

    def test_remove_mirrors_to_plan(self, tmp_path):
        root = _make_app(tmp_path)
        set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
        )
        r = set_field_interaction(
            str(root), page="employees/new", field="hra", mode="remove",
        )
        assert r["applied"]
        plan = json.loads((root / "plan.json").read_text())
        hra_in_plan = next(
            f for f in plan["pages"][0]["fields"] if f["name"] == "hra"
        )
        assert "interaction" not in hra_in_plan

    def test_case_insensitive_field_match_in_plan(self, tmp_path):
        root = _make_app(tmp_path)
        # Mutate plan to have different case
        plan_path = root / "plan.json"
        plan = json.loads(plan_path.read_text())
        for f in plan["pages"][0]["fields"]:
            if f["name"] == "hra":
                f["name"] = "HRA"
        plan_path.write_text(json.dumps(plan, indent=2))

        r = set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
        )
        assert r["applied"]
        plan = json.loads(plan_path.read_text())
        hra_in_plan = next(
            f for f in plan["pages"][0]["fields"] if f["name"].lower() == "hra"
        )
        assert "interaction" in hra_in_plan

    def test_missing_plan_json_does_not_block(self, tmp_path):
        root = _make_app(tmp_path)
        (root / "plan.json").unlink()
        r = set_field_interaction(
            str(root), page="employees/new", field="hra",
            interaction={"computed": {"formula": "basicSalary * 0.4"}},
        )
        assert r["applied"], r
        assert not any("plan.json" in p for p in r["edited_paths"])
