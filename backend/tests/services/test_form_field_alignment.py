"""Structural name-alignment: form field names get renamed to match
the target workflow's input names when they canonically match.

Runs inside ``scaffold_forms_from_workflow_inputs`` — same pass that
already reads workflow inputs to ADD missing fields, now also RENAMES
existing near-match fields. After this pass:

  - Form field names on a workflow-submitting page ARE the workflow
    input names.
  - No field_map needed downstream — identity mapping.
  - The fuzzy matcher in orphan_wiring_pass becomes defense-in-depth
    for the residual cases (fields with no canonical peer).
"""
from __future__ import annotations

import json
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────
# End-to-end via scaffold_forms_from_workflow_inputs
# ─────────────────────────────────────────────────────────────────────

def _write_plan(tmp: Path, plan: dict) -> None:
    (tmp / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "contracts" / "plan.json").write_text(
        json.dumps(plan), encoding="utf-8"
    )


def _write_page_schema(tmp: Path, route: str, form_field_names: list[str]) -> Path:
    """Nested layout matches _find_schema_for_route."""
    parts = [p for p in route.strip("/").split("/") if p] or ["index"]
    p = tmp / "src" / "schemas"
    for seg in parts[:-1]:
        p = p / seg
    p.mkdir(parents=True, exist_ok=True)
    schema_path = p / f"{parts[-1]}.json"
    fields = [
        {
            "component": "Input",
            "props": {"name": n, "label": n.replace("_", " ").title()},
        }
        for n in form_field_names
    ]
    schema_path.write_text(
        json.dumps({
            "route": route,
            "root": {
                "component": "Page",
                "children": [
                    {"component": "Form", "props": {}, "children": fields}
                ],
            },
        }),
        encoding="utf-8",
    )
    return schema_path


def _plan_with_workflow(
    workflow_input_names: list[str],
    page_route: str = "/candidates/new",
) -> dict:
    return {
        "pages": [{
            "name": "AddCandidate",
            "route": page_route,
            "submit": {
                "kind": "workflow",
                "target": "CreateCandidate",
                "field_map": {},
            },
        }],
        "workflows": [{
            "name": "CreateCandidate",
            "source": {"kind": "form", "page": "AddCandidate"},
            "inputs": [
                {
                    "name": n,
                    "type": "text",
                    "required": True,
                    "source": {"kind": "form_field", "field": n},
                }
                for n in workflow_input_names
            ],
        }],
    }


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────

def test_snake_case_field_gets_renamed_to_camel_case_workflow_input(tmp_path):
    from services.form_scaffold import scaffold_forms_from_workflow_inputs

    _write_plan(tmp_path, _plan_with_workflow(["firstName", "lastName"]))
    schema_path = _write_page_schema(
        tmp_path, "/candidates/new", ["first_name", "last_name"]
    )

    result = scaffold_forms_from_workflow_inputs(str(tmp_path))
    assert result.get("renamed", 0) == 2, result
    # Nothing to add — the renamed fields already cover the workflow inputs.
    assert result.get("added", 0) == 0

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    field_names = [
        (n.get("props") or {}).get("name")
        for n in schema["root"]["children"][0]["children"]
    ]
    assert field_names == ["firstName", "lastName"]


def test_rename_preserves_other_props():
    """The rename touches only ``props.name``; label/required/etc. stay."""
    from services.form_scaffold import scaffold_forms_from_workflow_inputs
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write_plan(tmp, _plan_with_workflow(["cvUrl"]))
        parts = ["candidates", "new"]
        p = tmp / "src" / "schemas"
        for seg in parts[:-1]:
            p = p / seg
        p.mkdir(parents=True, exist_ok=True)
        schema_path = p / "new.json"
        schema_path.write_text(json.dumps({
            "route": "/candidates/new",
            "root": {
                "component": "Page",
                "children": [{
                    "component": "Form",
                    "children": [{
                        "component": "FileUpload",
                        "props": {
                            "name": "cv_url",
                            "label": "Upload your CV",
                            "required": True,
                            "accept": ".pdf,.doc",
                        },
                    }],
                }],
            },
        }), encoding="utf-8")

        scaffold_forms_from_workflow_inputs(str(tmp))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        node = schema["root"]["children"][0]["children"][0]
        assert node["props"]["name"] == "cvUrl"
        # Other props survived the rename.
        assert node["props"]["label"] == "Upload your CV"
        assert node["props"]["required"] is True
        assert node["props"]["accept"] == ".pdf,.doc"
        # Component didn't change.
        assert node["component"] == "FileUpload"


def test_no_rename_when_names_already_match(tmp_path):
    from services.form_scaffold import scaffold_forms_from_workflow_inputs

    _write_plan(tmp_path, _plan_with_workflow(["firstName"]))
    schema_path = _write_page_schema(tmp_path, "/candidates/new", ["firstName"])

    result = scaffold_forms_from_workflow_inputs(str(tmp_path))
    assert result.get("renamed", 0) == 0
    assert result.get("added", 0) == 0

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    field_names = [
        (n.get("props") or {}).get("name")
        for n in schema["root"]["children"][0]["children"]
    ]
    assert field_names == ["firstName"]


def test_no_rename_for_unrelated_fields(tmp_path):
    """A form field with no canonical peer in workflow inputs must
    not be renamed — leave it alone (it might be a UI-only field)."""
    from services.form_scaffold import scaffold_forms_from_workflow_inputs

    _write_plan(tmp_path, _plan_with_workflow(["firstName"]))
    schema_path = _write_page_schema(
        tmp_path, "/candidates/new", ["first_name", "unrelated_field"]
    )

    scaffold_forms_from_workflow_inputs(str(tmp_path))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    field_names = [
        (n.get("props") or {}).get("name")
        for n in schema["root"]["children"][0]["children"]
    ]
    # first_name renamed; unrelated_field untouched.
    assert "firstName" in field_names
    assert "unrelated_field" in field_names
    assert "first_name" not in field_names


def test_no_rename_when_target_name_already_present(tmp_path):
    """If the form has BOTH ``first_name`` AND ``firstName``, renaming
    would collide. Leave ``first_name`` alone — the workflow's input
    is already covered by the existing ``firstName``."""
    from services.form_scaffold import scaffold_forms_from_workflow_inputs

    _write_plan(tmp_path, _plan_with_workflow(["firstName"]))
    schema_path = _write_page_schema(
        tmp_path, "/candidates/new", ["first_name", "firstName"]
    )

    result = scaffold_forms_from_workflow_inputs(str(tmp_path))
    assert result.get("renamed", 0) == 0
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    field_names = [
        (n.get("props") or {}).get("name")
        for n in schema["root"]["children"][0]["children"]
    ]
    assert "first_name" in field_names
    assert "firstName" in field_names


def test_mixed_rename_and_add(tmp_path):
    """A form with one field that gets renamed, and one workflow input
    that doesn't exist yet (needs adding). Both branches run in one
    pass."""
    from services.form_scaffold import scaffold_forms_from_workflow_inputs

    _write_plan(tmp_path, _plan_with_workflow(["firstName", "lastName", "email"]))
    schema_path = _write_page_schema(
        tmp_path, "/candidates/new", ["first_name", "email"]
    )

    result = scaffold_forms_from_workflow_inputs(str(tmp_path))
    # first_name → firstName; lastName appended; email already matches.
    assert result.get("renamed", 0) == 1
    assert result.get("added", 0) == 1

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    field_names = [
        (n.get("props") or {}).get("name")
        for n in schema["root"]["children"][0]["children"]
    ]
    assert set(field_names) == {"firstName", "email", "lastName"}


def test_return_shape_is_backward_compatible(tmp_path):
    """Existing callers only read ``added`` and ``files``. New
    ``renamed`` key is additive."""
    from services.form_scaffold import scaffold_forms_from_workflow_inputs

    _write_plan(tmp_path, _plan_with_workflow(["firstName"]))
    _write_page_schema(tmp_path, "/candidates/new", ["first_name"])

    result = scaffold_forms_from_workflow_inputs(str(tmp_path))
    assert "added" in result
    assert "files" in result
    assert "renamed" in result
    assert result["renamed"] == 1
    assert result["files"] == 1
