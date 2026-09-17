"""A screen's own values: declared, changed, judged.

The calculator that shipped had a display column in a `CalculatorSession`
table, a workflow per key, and no key that did anything. `clientState` and
`clientAction` are the vocabulary that was missing; these tests hold the four
places that vocabulary has to be understood — the catalogue, the action union,
the floor that judges a composed page, and the completeness gate that would
otherwise refuse a page for reading its own display.
"""
import json
from pathlib import Path

import pytest

from services.a2ui_authority import _floor_findings, is_standalone
from services.a2ui_to_forge import dangling_bindings
from services.blueprint.functional_completeness import _action_props, page_findings
from services.blueprint.page_planner import (
    load_catalog, validate_props, validate_template,
)
from services.client_state_anatomy import client_state_findings, tool_findings

ROOT = Path(__file__).resolve().parents[3]


def _calculator(**over) -> dict:
    """A page that keeps a display and changes it — nothing stored."""
    body = {
        "page": "calculator",
        "route": "/",
        "clientState": [
            {"name": "display", "type": "string", "initial": "0",
             "description": "what the screen shows"},
        ],
        "dataSources": [],
        "root": {"type": "Stack", "props": {}, "children": [
            {"type": "Text", "props": {"value": "{{state.display}}"}},
            {"type": "Button", "props": {
                "label": "7",
                "clientAction": {"kind": "compute", "target": "display",
                                 "formula": "display + '7'"}}},
            {"type": "Button", "props": {
                "label": "C",
                "clientAction": {"kind": "set", "target": "display",
                                 "value": "0"}}},
        ]},
    }
    body.update(over)
    return body


def test_the_catalogue_offers_a_client_action():
    """A composer can only author what the catalogue advertises."""
    catalog = json.loads(
        (ROOT / "backend/contracts/component-catalog.json").read_text())
    entries = catalog["components"] if isinstance(catalog, dict) else catalog
    button = (entries["Button"] if isinstance(entries, dict)
              else next(e for e in entries if e.get("name") == "Button"))
    assert "clientAction" in json.dumps(button)


def test_a_client_action_is_a_control_doing_something():
    """Without this a key that does the only thing a key can do is refused as
    a label with a border, and the composer is pushed back to inventing a
    workflow and a table."""
    assert "clientAction" in _action_props()


def test_a_calculator_composes_against_the_real_catalogue():
    catalog = load_catalog()
    body = _calculator()
    assert validate_template(body, catalog) == []
    assert validate_props({"root": body["root"]}, catalog) == []


def test_the_page_reads_its_own_display_without_a_data_source():
    """`{{state.display}}` resolves against `clientState`, not a fetch."""
    body = _calculator()
    assert dangling_bindings(body) == []
    assert dangling_bindings({**body, "clientState": []}) == ["state"]


def test_the_completeness_gate_accepts_a_screen_with_no_records():
    doc = {
        "pages": [{"id": "calculator", "route": "/", "name": "Calculator",
                   "module": "tools"}],
        "workflows": [], "data": {}, "security": {}, "businessRules": [],
        "pageLayouts": [_calculator()],
    }
    assert page_findings(doc) == []


def test_a_control_writing_somewhere_undeclared_is_refused():
    """The mirror of a dangling binding. Writing to a value nobody declared
    changes nothing anyone can see, and it fails silently."""
    body = _calculator()
    body["root"]["children"][1]["props"]["clientAction"]["target"] = "total"
    rules = [f["rule"] for f in client_state_findings("/", body)]
    assert "client_action_target_undeclared" in rules


def test_a_value_nothing_touches_is_refused():
    """Declared, never bound, never computed from. The page keeps a number in
    its head and shows a blank."""
    body = _calculator()
    body["clientState"].append(
        {"name": "memory", "type": "number", "initial": 0})
    findings = client_state_findings("/", body)
    assert [f["rule"] for f in findings] == ["client_state_never_read"]
    assert findings[0]["slot"] == "memory"


def test_an_intermediate_value_is_not_dead():
    """A calculator's pending operator is read by formulas and displayed
    nowhere, and that is correct. Refusing it would refuse the calculator."""
    body = _calculator()
    body["clientState"].append(
        {"name": "pending", "type": "string", "initial": ""})
    body["root"]["children"][2]["props"]["clientAction"] = {
        "kind": "compute", "target": "display", "formula": "pending + display"}
    assert client_state_findings("/", body) == []


def test_a_server_backed_page_is_judged_exactly_as_before():
    """Silence on every page that declares none and authors none."""
    plain = {"dataSources": [{"name": "nurses", "op": "list"}],
             "root": {"type": "Table", "props": {"data": "{{nurses}}"}}}
    assert client_state_findings("/nurses", plain) == []


def test_the_shipped_calculator_is_refused():
    """A table to hold the display, a workflow per key. Data sources are what
    a self-contained tool does not need, so having one does not excuse it."""
    shipped = {
        "dataSources": [{"name": "calculatorsessions", "op": "list"}],
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "7", "workflow": "FLOW-001"}},
        ]},
    }
    assert "tool_has_no_values" in [f["rule"] for f in tool_findings("/", shipped)]


def test_a_tool_of_decoration_is_refused():
    inert = {"root": {"type": "Stack", "children": [
        {"type": "Button", "props": {"label": "7"}}]}}
    rules = [f["rule"] for f in tool_findings("/", inert)]
    assert "tool_controls_are_inert" in rules


def test_a_real_tool_clears_the_floor():
    assert tool_findings("/", _calculator()) == []


def test_the_floor_reports_the_tool_rules_only_for_a_tool():
    """`is_standalone` is the narrow reading — no pattern AND no entity — so a
    page about records is judged by the record floors and nothing new."""
    contract = {"id": "calculator", "route": "/", "data": {}}
    assert is_standalone("", contract)
    assert not is_standalone("", {"data": {"primaryEntity": "Nurse"}})
    assert not is_standalone("list", contract)

    shipped = {
        "dataSources": [{"name": "calculatorsessions", "op": "list"}],
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "7", "workflow": "FLOW-001"}}]},
    }
    rules = [f.get("rule") for f in
             _floor_findings("", "/", shipped, {"entities": []}, contract)]
    assert "tool_has_no_values" in rules


def test_a_hybrid_is_both_and_refused_for_neither():
    """A form that totals as you type and submits the total. The same Button
    carries a client action and a workflow; both run."""
    hybrid = {
        "clientState": [{"name": "total", "type": "number", "initial": 0}],
        "dataSources": [{"name": "orders", "op": "list"}],
        "root": {"type": "Stack", "children": [
            {"type": "Text", "props": {"value": "{{state.total}}"}},
            {"type": "Button", "props": {
                "label": "Submit", "workflow": "FLOW-001",
                "clientAction": {"kind": "compute", "target": "total",
                                 "formula": "total + 1"}}},
        ]},
    }
    assert client_state_findings("/orders", hybrid) == []
    assert dangling_bindings(hybrid) == []


# ------------------------------------------- one press, several values

def _clear_key(actions):
    return {
        "page": "calculator", "route": "/",
        "clientState": [
            {"name": "display", "type": "string", "initial": "0"},
            {"name": "error", "type": "boolean"},
            {"name": "errorMessage", "type": "string"},
        ],
        "dataSources": [],
        "root": {"type": "Stack", "props": {}, "children": [
            {"type": "Text", "props": {
                "content": "{{state.display}} {{state.error}} {{state.errorMessage}}"}},
            {"id": "clear", "type": "Button",
             "props": {"label": "C", "clientAction": actions}},
        ]},
    }


CLEAR = [
    {"kind": "set", "target": "display", "value": "0"},
    {"kind": "set", "target": "error", "value": False},
    {"kind": "set", "target": "errorMessage", "value": ""},
]


def test_a_clear_key_may_change_three_values_in_one_press():
    """MEASURED ON A LIVE RUN. The composer authored exactly this and every
    attempt at the page was refused, because the contract allowed one action
    per control. The instinct was right and the contract was too narrow."""
    body = _clear_key(CLEAR)
    catalog = load_catalog()
    assert validate_props({"root": body["root"]}, catalog) == []
    assert validate_template(body, catalog) == []
    assert client_state_findings("/", body) == []


def test_one_action_is_still_one_action():
    body = _clear_key({"kind": "set", "target": "display", "value": "0"})
    assert validate_props({"root": body["root"]}, load_catalog()) == []
    assert client_state_findings("/", body) == []


def test_a_press_that_writes_one_value_twice_is_refused():
    """The changes of a press are applied TOGETHER, each reading the state
    before it — so a second write to the same value silently replaces the
    first, and which one wins is a fact about list position, not about what
    the page means."""
    body = _clear_key(CLEAR + [{"kind": "set", "target": "display", "value": "1"}])
    rules = [f["rule"] for f in client_state_findings("/", body)]
    assert rules == ["client_action_writes_twice"]


def test_every_action_in_a_press_is_checked_against_what_is_declared():
    body = _clear_key(CLEAR + [{"kind": "set", "target": "ghost", "value": 1}])
    rules = [f["rule"] for f in client_state_findings("/", body)]
    assert "client_action_target_undeclared" in rules


def test_nonsense_in_a_list_is_still_nonsense():
    body = _clear_key([{"kind": "nope", "target": "display"}])
    assert validate_props({"root": body["root"]}, load_catalog())
