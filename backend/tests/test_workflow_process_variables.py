"""Tests for the process-variable derivation helper."""

from __future__ import annotations

import pytest

from services.workflow_process_variables import (
    derive_process_variables,
    strip_source,
)


def _node(nid: str, cfg: dict, ntype: str = "action") -> dict:
    return {
        "id": nid,
        "type": ntype,
        "data": {"label": nid, "nodeType": ntype, "config": cfg},
    }


# ---------------------------------------------------------------------------
# planner-authored path
# ---------------------------------------------------------------------------


def test_returns_empty_when_nothing_declared():
    assert derive_process_variables({}, []) == []


def test_carries_planner_authored_entries_verbatim():
    wf = {
        "processVariables": [
            {"name": "orderId", "type": "string", "required": True, "description": "the order"},
            {"name": "orderTotal", "type": "number"},
        ]
    }
    got = derive_process_variables(wf, [])
    assert len(got) == 2
    assert got[0]["name"] == "orderId"
    assert got[0]["type"] == "string"
    assert got[0]["required"] is True
    assert got[0]["description"] == "the order"
    assert got[0]["source"] == "planner"
    assert got[1]["type"] == "number"
    assert "required" not in got[1]


def test_planner_entries_with_blank_or_missing_name_are_dropped():
    wf = {"processVariables": [
        {"name": "", "type": "string"},
        {"type": "number"},
        {"name": "keep", "type": "string"},
    ]}
    got = derive_process_variables(wf, [])
    assert [e["name"] for e in got] == ["keep"]


def test_bogus_type_falls_back_to_string():
    wf = {"processVariables": [{"name": "x", "type": "widget"}]}
    got = derive_process_variables(wf, [])
    assert got[0]["type"] == "string"


# ---------------------------------------------------------------------------
# set_variable node derivation
# ---------------------------------------------------------------------------


def test_set_variable_node_becomes_process_var():
    nodes = [_node("set1", {"actionType": "set_variable", "variableName": "retryCount", "variableValue": 0})]
    got = derive_process_variables({}, nodes)
    assert len(got) == 1
    assert got[0]["name"] == "retryCount"
    assert got[0]["type"] == "number"
    assert got[0]["source"] == "set_variable:set1"


def test_set_variable_accepts_value_alias():
    nodes = [_node("s", {"actionType": "set_variable", "variableName": "flag", "value": True})]
    got = derive_process_variables({}, nodes)
    assert got[0]["type"] == "boolean"


def test_set_variable_without_name_is_dropped():
    nodes = [_node("s", {"actionType": "set_variable", "variableValue": 1})]
    assert derive_process_variables({}, nodes) == []


def test_non_set_variable_action_is_ignored():
    nodes = [_node("s", {"actionType": "db_insert", "variableName": "orderId"})]
    assert derive_process_variables({}, nodes) == []


# ---------------------------------------------------------------------------
# output-mapping promotion
# ---------------------------------------------------------------------------


def test_promoted_output_becomes_process_var():
    nodes = [_node("create", {
        "actionType": "db_insert",
        "outputMappings": [
            {"output": "inserted.id", "processVar": "createdOrderId"},
            {"output": "inserted.total", "processVar": ""},  # not promoted → skipped
        ],
    })]
    got = derive_process_variables({}, nodes)
    assert [e["name"] for e in got] == ["createdOrderId"]
    assert got[0]["source"] == "output:create.inserted.id"


# ---------------------------------------------------------------------------
# merge ordering — planner wins
# ---------------------------------------------------------------------------


def test_planner_wins_when_name_collides_with_derived():
    wf = {"processVariables": [{"name": "orderId", "type": "uuid", "description": "the order"}]}
    nodes = [_node("s", {"actionType": "set_variable", "variableName": "orderId", "variableValue": 42})]
    got = derive_process_variables(wf, nodes)
    assert len(got) == 1
    assert got[0]["type"] == "uuid"                # planner's uuid, not derived "number"
    assert got[0]["description"] == "the order"    # planner's description carried
    assert got[0]["source"] == "planner"


def test_set_variable_wins_when_output_mapping_collides():
    nodes = [
        _node("s1", {"actionType": "set_variable", "variableName": "shared", "variableValue": "x"}),
        _node("s2", {"actionType": "db_insert",
                     "outputMappings": [{"output": "id", "processVar": "shared"}]}),
    ]
    got = derive_process_variables({}, nodes)
    assert len(got) == 1
    assert got[0]["source"] == "set_variable:s1"


# ---------------------------------------------------------------------------
# strip_source
# ---------------------------------------------------------------------------


def test_strip_source_removes_breadcrumb():
    entries = [{"name": "x", "type": "string", "source": "planner"}]
    stripped = strip_source(entries)
    assert stripped == [{"name": "x", "type": "string"}]
    # original unchanged
    assert "source" in entries[0]


# ---------------------------------------------------------------------------
# defensive shapes
# ---------------------------------------------------------------------------


def test_non_dict_planner_entries_and_nodes_are_skipped():
    wf = {"processVariables": ["banana", 3, None, {"name": "ok"}]}
    nodes = ["nope", None, _node("n", {"actionType": "set_variable", "variableName": "y", "variableValue": 1})]
    got = derive_process_variables(wf, nodes)
    names = [e["name"] for e in got]
    assert "ok" in names and "y" in names
