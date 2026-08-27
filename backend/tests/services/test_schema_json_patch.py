"""Tests for services.schema_json_patch — deterministic JSON ops on a
page schema. Powers the drag-and-drop form builder's PUT endpoint.

DND-1. All ops are pure functions:
  insert(schema, at_path, index, component, props)
  delete(schema, at_path)
  reorder(schema, parent_path, from_index, to_index)
  update_props(schema, at_path, props)

`at_path` is a list of str|int addressing a node inside `schema`.
Everything is copy-based — no in-place mutation. Errors raise
:class:`PatchError` with a human-readable message so the API can
surface it to the UI.
"""
from __future__ import annotations

from copy import deepcopy

import pytest


def _sample() -> dict:
    """A realistic mini-form schema mirroring what build_form_page emits."""
    return {
        "schemaVersion": "2",
        "id": "sample",
        "root": {
            "type": "Stack",
            "children": [
                {"type": "Heading", "props": {"content": "Add User", "level": 1}},
                {
                    "type": "Card",
                    "children": [
                        {
                            "type": "Form",
                            "props": {"workflow": "CreateUser"},
                            "children": [
                                {
                                    "type": "Stack",
                                    "children": [
                                        {"type": "Input", "props": {"name": "email", "label": "Email"}},
                                        {"type": "Input", "props": {"name": "name",  "label": "Name"}},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    }


# --------------------------------------------------------------------------- #
# insert
# --------------------------------------------------------------------------- #

def test_insert_appends_at_index_zero():
    from services.schema_json_patch import insert

    schema = _sample()
    new = insert(
        schema,
        at_path=["root", "children", 1, "children", 0, "children", 0, "children"],
        index=0,
        component="Input",
        props={"name": "phone", "label": "Phone"},
    )
    # Original untouched (pure).
    stack = schema["root"]["children"][1]["children"][0]["children"][0]
    assert [c["props"]["name"] for c in stack["children"]] == ["email", "name"]
    # New has phone at position 0.
    new_stack = new["root"]["children"][1]["children"][0]["children"][0]
    assert [c["props"]["name"] for c in new_stack["children"]] == ["phone", "email", "name"]
    assert new_stack["children"][0]["type"] == "Input"


def test_insert_in_middle():
    from services.schema_json_patch import insert

    new = insert(
        _sample(),
        at_path=["root", "children", 1, "children", 0, "children", 0, "children"],
        index=1,
        component="PasswordInput",
        props={"name": "password", "label": "Password"},
    )
    stack = new["root"]["children"][1]["children"][0]["children"][0]
    assert [c["props"]["name"] for c in stack["children"]] == ["email", "password", "name"]


def test_insert_at_end():
    from services.schema_json_patch import insert

    new = insert(
        _sample(),
        at_path=["root", "children", 1, "children", 0, "children", 0, "children"],
        index=2,
        component="Textarea",
        props={"name": "bio", "label": "Bio"},
    )
    stack = new["root"]["children"][1]["children"][0]["children"][0]
    assert [c["props"]["name"] for c in stack["children"]] == ["email", "name", "bio"]


def test_insert_beyond_end_appends():
    """Out-of-range index (index > len) appends rather than crashing.
    Matches JS Array.splice — dnd-kit passes a large index for 'drop at end'."""
    from services.schema_json_patch import insert

    new = insert(
        _sample(),
        at_path=["root", "children", 1, "children", 0, "children", 0, "children"],
        index=999,
        component="Input",
        props={"name": "extra"},
    )
    stack = new["root"]["children"][1]["children"][0]["children"][0]
    assert stack["children"][-1]["props"]["name"] == "extra"


def test_insert_into_non_list_raises():
    from services.schema_json_patch import insert, PatchError

    with pytest.raises(PatchError, match="not a list"):
        insert(_sample(), at_path=["root", "children", 0, "props"], index=0,
               component="Input", props={"name": "x"})


def test_insert_at_bad_path_raises():
    from services.schema_json_patch import insert, PatchError

    with pytest.raises(PatchError, match="path"):
        insert(_sample(), at_path=["root", "children", 99, "children"], index=0,
               component="Input", props={"name": "x"})


def test_insert_component_defaults_props_to_empty():
    from services.schema_json_patch import insert

    new = insert(
        _sample(),
        at_path=["root", "children", 1, "children", 0, "children", 0, "children"],
        index=0,
        component="Divider",
    )
    stack = new["root"]["children"][1]["children"][0]["children"][0]
    assert stack["children"][0] == {"type": "Divider", "props": {}}


# --------------------------------------------------------------------------- #
# delete
# --------------------------------------------------------------------------- #

def test_delete_removes_node_at_path():
    from services.schema_json_patch import delete

    new = delete(_sample(), at_path=["root", "children", 1, "children", 0, "children", 0, "children", 0])
    stack = new["root"]["children"][1]["children"][0]["children"][0]
    assert [c["props"]["name"] for c in stack["children"]] == ["name"]
    # Original untouched.
    assert len(_sample()["root"]["children"][1]["children"][0]["children"][0]["children"]) == 2


def test_delete_at_root_raises():
    from services.schema_json_patch import delete, PatchError

    with pytest.raises(PatchError, match="root"):
        delete(_sample(), at_path=[])


def test_delete_bad_path_raises():
    from services.schema_json_patch import delete, PatchError

    with pytest.raises(PatchError, match="path"):
        delete(_sample(), at_path=["root", "children", 99])


# --------------------------------------------------------------------------- #
# reorder
# --------------------------------------------------------------------------- #

def test_reorder_moves_child_between_positions():
    from services.schema_json_patch import reorder

    # Move email (idx 0) to after name (idx 1) → [name, email]
    new = reorder(
        _sample(),
        parent_path=["root", "children", 1, "children", 0, "children", 0, "children"],
        from_index=0,
        to_index=1,
    )
    stack = new["root"]["children"][1]["children"][0]["children"][0]
    assert [c["props"]["name"] for c in stack["children"]] == ["name", "email"]


def test_reorder_noop_when_same_index():
    from services.schema_json_patch import reorder

    new = reorder(
        _sample(),
        parent_path=["root", "children", 1, "children", 0, "children", 0, "children"],
        from_index=0,
        to_index=0,
    )
    stack = new["root"]["children"][1]["children"][0]["children"][0]
    assert [c["props"]["name"] for c in stack["children"]] == ["email", "name"]


def test_reorder_out_of_bounds_from_raises():
    from services.schema_json_patch import reorder, PatchError

    with pytest.raises(PatchError, match="from_index"):
        reorder(_sample(),
                parent_path=["root", "children", 1, "children", 0, "children", 0, "children"],
                from_index=5, to_index=0)


def test_reorder_clamps_to_index_to_end():
    """to_index > len is treated as end — matches DnD "drop at end" gesture."""
    from services.schema_json_patch import reorder

    # 2 children; to_index=99 → append at end. Move 0→end = [name, email].
    new = reorder(
        _sample(),
        parent_path=["root", "children", 1, "children", 0, "children", 0, "children"],
        from_index=0,
        to_index=99,
    )
    stack = new["root"]["children"][1]["children"][0]["children"][0]
    assert [c["props"]["name"] for c in stack["children"]] == ["name", "email"]


# --------------------------------------------------------------------------- #
# update_props
# --------------------------------------------------------------------------- #

def test_update_props_merges_into_existing():
    from services.schema_json_patch import update_props

    new = update_props(
        _sample(),
        at_path=["root", "children", 1, "children", 0, "children", 0, "children", 0],
        props={"label": "Email address", "required": True},
    )
    node = new["root"]["children"][1]["children"][0]["children"][0]["children"][0]
    assert node["props"] == {"name": "email", "label": "Email address", "required": True}


def test_update_props_on_node_without_props_creates_props():
    """A Divider ships as {type: 'Divider'} with no props. update_props must add one."""
    from services.schema_json_patch import update_props, insert

    schema = insert(_sample(),
                    at_path=["root", "children", 1, "children", 0, "children", 0, "children"],
                    index=0, component="Divider")
    schema = update_props(schema,
                          at_path=["root", "children", 1, "children", 0, "children", 0, "children", 0],
                          props={"variant": "muted"})
    node = schema["root"]["children"][1]["children"][0]["children"][0]["children"][0]
    assert node["props"] == {"variant": "muted"}


def test_update_props_bad_path_raises():
    from services.schema_json_patch import update_props, PatchError

    with pytest.raises(PatchError, match="path"):
        update_props(_sample(), at_path=["root", "children", 99], props={})
