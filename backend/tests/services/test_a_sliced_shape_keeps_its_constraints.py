"""The schema an agent is handed still says what the contract says.

`writable_shapes` cuts one agent's sections out of the contract and hands them
over as a standalone JSON Schema — and the model call is structured-output
constrained against it, so what that schema states is what the model can write.

Every `$ref` inside the slice still pointed into the whole document:

    "references": {"$ref": "#/properties/pages/items/properties/data/
                            properties/primaryEntity"}

The slice has no `#/properties/pages`, so the ref resolved to nothing and the
constraint never travelled. Twenty-eight of them were in that state across four
agents.

Measured: `data_model` produced a thirty-entity model of a refund framework and
put `references: ""` on three fields. The contract requires `^ENTITY-\\d{3,}$`,
the whole document was refused, and the thirty entities were lost. The agent
had never been told the pattern — only a description reading "Stable ENTITY
identifier", and prose loses to schema.
"""
from __future__ import annotations

import json

from services.blueprint.executors import writable_shapes

AGENTS = ("data_model", "workflow", "security")


def _blob(agent: str) -> str:
    return json.dumps(writable_shapes(agent))


def test_the_entity_reference_carries_its_pattern():
    """The one that cost thirty entities. With the pattern inlined, `""` is
    not discouraged — it is unrepresentable, because the reply is
    schema-constrained."""
    shape = writable_shapes("data_model")["data.entities"]
    field = shape["properties"]["fields"]["items"]["properties"]["references"]
    assert field["pattern"] == r"^ENTITY-\d{3,}$"


def test_no_agent_is_handed_a_pointer_to_nothing():
    for agent in AGENTS:
        assert '"$ref"' not in _blob(agent), (
            f"{agent}'s schema still points into a document it does not have"
        )


def test_a_recursive_ref_is_left_alone():
    """`patternTemplates.root` contains itself. Expanding it does not
    terminate, and one unresolvable pointer is a smaller loss than a schema
    that never finishes building."""
    blob = _blob("a2ui_pages")
    refs = [r for r in json.loads(blob).get("pageLayouts", {}).get("properties", {}).values()
            if isinstance(r, dict) and "$ref" in r]
    assert '"$ref"' in blob
    assert "patternTemplates" in blob


def test_the_local_description_survives_inlining():
    """A field's own description was written for that field; the target's is
    generic. Losing it would trade one kind of vagueness for another."""
    shape = writable_shapes("data_model")["data.entities"]
    field = shape["properties"]["fields"]["items"]["properties"]["references"]
    assert "ENTITY" in field.get("description", "")


def test_withheld_fields_are_still_withheld():
    """Inlining must not reintroduce what §12 removes: identity is assigned,
    not authored."""
    shape = writable_shapes("data_model")["data.entities"]
    assert "id" not in shape["properties"]
    assert "id" not in shape.get("required", [])


def test_an_unfollowable_ref_is_left_rather_than_dropped():
    """A ref this cannot resolve stays as it was. Silently deleting it would
    replace a constraint nobody can see with no constraint at all."""
    from services.blueprint.executors import _inline_refs

    node = {"$ref": "#/properties/nope/items"}
    assert _inline_refs(node, {"properties": {}}) == node
