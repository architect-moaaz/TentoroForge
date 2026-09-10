"""`config` was a free-form bag, so `sets` had no shape and the consumer had one.

`workflows[].steps[].config` is declared `additionalProperties: {}`. Anything
validates. `project_workflows` then read `config["sets"]` as a column-to-value
map and called `.items()` on it.

One real build emitted all 56 of them as lists of prose —

    ["status = in_triage", "lastActionAt = now"]

— which validated perfectly, raised `AttributeError: 'list' object has no
attribute 'items'`, killed the `integration` node, and took thirty workflow
definitions and the `testing` node downstream with it. The Blueprint was
accepted and the application lost its workflows.

Two properties, at the two levels they belong to:

  * the contract types `sets`, so the shape is unrepresentable at source;
  * the projection survives a shape it cannot honour, naming it, because
    losing one step's overrides beats losing every workflow in the app.
"""
import json
import pathlib

import pytest

from services.blueprint.projection import project_workflows

_CONTRACT = (pathlib.Path(__file__).resolve().parents[2]
             / "contracts" / "blueprint.schema.json")


def _step_config_schema() -> dict:
    c = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    return c["properties"]["workflows"]["items"]["properties"]["steps"]["items"]["properties"]["config"]


def test_the_contract_types_sets_as_a_map():
    """Structured output enforces `type`, so a list becomes unrepresentable."""
    sets = _step_config_schema().get("properties", {}).get("sets")
    assert sets is not None, "`sets` is undeclared, so any shape validates"
    assert sets["type"] == "object"


def test_a_column_may_be_set_to_any_scalar():
    """THE CONSTRAINT IS THE MAP, NOT THE VALUE TYPE. Typing the values
    `string` rejected 33 existing Blueprints on `closedAt: null` and
    `isCurrent: true` — both of which are exactly what those columns hold.
    Over-constraining here does not catch the list bug any better; it just
    refuses correct work."""
    allowed = _step_config_schema()["properties"]["sets"]["additionalProperties"]["type"]
    for scalar in ("string", "number", "boolean", "null"):
        assert scalar in allowed, f"a column cannot be set to {scalar}"
    assert "array" not in allowed and "object" not in allowed, (
        "a column holds one value; allowing a list is the bug this prevents"
    )


def _doc(sets):
    return {
        "application": {"id": "app", "name": "App"},
        "data": {"entities": [{
            "id": "ENTITY-001", "name": "Case", "table": "cases",
            "fields": [{"name": "title", "type": "string"},
                       {"name": "status", "type": "string"}],
        }]},
        "workflows": [{
            "id": "FLOW-001", "name": "Raise case", "entity": "ENTITY-001",
            "steps": [{"key": "s1", "name": "Insert", "type": "action",
                       "entity": "ENTITY-001",
                       "config": {"actionType": "db_insert", "sets": sets}}],
        }],
    }


@pytest.mark.parametrize("sets", [
    ["status = in_triage", "lastActionAt = now"],   # the shape that crashed
    "status = open",
    42,
])
def test_a_sets_shape_the_projection_cannot_honour_is_skipped_not_fatal(sets, tmp_path):
    result = project_workflows(_doc(sets), tmp_path)
    assert len(result["files"]) == 1, "the workflow must still be projected"


def test_a_well_formed_sets_still_reaches_the_projection(tmp_path):
    """The floor must not swallow the working case: `sets` is where a workflow
    states the values a person never types, and dropping those silently is the
    not-null insert failure this exists to prevent."""
    result = project_workflows(_doc({"status": "Open"}), tmp_path)
    assert len(result["files"]) == 1
    written = json.loads((tmp_path / result["files"][0]).read_text(encoding="utf-8")) \
        if (tmp_path / result["files"][0]).exists() else {}
    assert "Open" in json.dumps(written), "the declared value never reached the artifact"


def test_no_sets_at_all_is_normal(tmp_path):
    """Most steps declare none, and that is not a defect."""
    doc = _doc(None)
    doc["workflows"][0]["steps"][0]["config"].pop("sets")
    assert len(project_workflows(doc, tmp_path)["files"]) == 1
