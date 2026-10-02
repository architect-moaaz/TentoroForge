"""The contract can say a screen is a tool, and nothing downstream disagrees.

Asked for "a simple arithmetic calculator", `page_contracts` labelled it
`dashboard`. It was not a careless choice: the eighteen-value pattern enum
named nothing but ways of showing, entering or arranging RECORDS, and the only
slot an application with no entities was handed arrived pre-labelled
`dashboard`. The agent filled the slot exactly as told.

Everything then behaved correctly on a false premise. The dashboard floor
demanded three KPI tiles, a chart and a recent-activity surface; a calculator
has no records to count, plot or list; the composer is separately forbidden
from writing a number it cannot bind. Every composition was refused, and the
page author bolted a chart bound to {{resultHistory}} and a feed bound to
{{keystrokeLog}} onto a keypad to get past it — its own rationale says so.

These hold the whole chain: the enum can name it, the slot stops asserting it,
and the three floors that would have judged it as a dashboard no longer do.
"""
import json
from pathlib import Path

from services.a2ui_authority import (
    STANDALONE_FAMILY, _family_of, _floor_findings, is_standalone,
)
from services.blueprint.executors import NODE_TASKS
from services.blueprint.page_planner import page_slots
from services.dashboard_anatomy import dashboard_findings
from services.page_kind_anatomy import page_family, page_kind_findings

ROOT = Path(__file__).resolve().parents[3]

KEYPAD = {
    "meta": {"pattern": "tool"},
    "root": {"type": "Container", "children": [
        {"type": "Text", "props": {"content": "{{state.display}}"}},
        {"type": "Grid", "children": [
            {"type": "Button", "props": {
                "label": "7",
                "clientAction": {"kind": "compute", "target": "display",
                                 "formula": "display + '7'"}}}]},
    ]},
    "clientState": [{"name": "display", "type": "string", "initial": "0"}],
    "dataSources": [],
}


def test_the_contract_can_name_a_tool():
    schema = json.loads(
        (ROOT / "backend/contracts/blueprint.schema.json").read_text())
    enum = schema["properties"]["pages"]["items"]["properties"]["pattern"]["enum"]
    assert "tool" in enum


def test_the_home_slot_no_longer_asserts_a_dashboard():
    """This is where the calculator became a dashboard. A slot is the answer
    space, so a pre-labelled one is not a hint — it is the instruction."""
    tool_app = page_slots({"data": {"entities": []}})
    assert tool_app[0]["pages"][0]["pattern"] == "tool"


def test_an_application_with_records_still_opens_on_a_dashboard():
    with_records = page_slots({"data": {"entities": [
        {"id": "ENTITY-001", "name": "Nurse"}]}})
    assert with_records[0]["pages"][0]["pattern"] == "dashboard"


def test_the_agent_is_told_when_the_value_is_the_right_one():
    """Naming the value in the enum is not enough."""
    task = NODE_TASKS["page_contracts"]
    assert "`tool`" in task
    assert "primaryEntity" in task


def test_a_tool_is_judged_by_what_a_tool_owes():
    assert page_family("tool") == STANDALONE_FAMILY
    assert _family_of("tool", "/") == STANDALONE_FAMILY
    assert is_standalone("tool", {"data": {}})
    # A real one clears its own floor.
    assert page_kind_findings("tool", "/", KEYPAD) == []


def test_a_tool_is_not_held_to_the_dashboard_floor():
    """Three call sites judged this page. The composer's floor, and the two
    post-projection gates that read the route alone."""
    contract = {"id": "PAGE-001", "route": "/", "pattern": "tool", "data": {}}
    assert _floor_findings("tool", "/", KEYPAD, {"entities": []}, contract) == []
    assert dashboard_findings("/", KEYPAD, {"entities": []}) == []


def test_a_page_that_declares_nothing_is_judged_exactly_as_before():
    """Only a contract that NAMES a non-dashboard pattern is excused."""
    undeclared = {**KEYPAD, "meta": {}}
    rules = [f["rule"] for f in dashboard_findings("/", undeclared, {"entities": []})]
    assert "dashboard_no_kpis" in rules
    assert "dashboard_no_chart" in rules


def test_a_real_dashboard_is_still_held_to_it():
    declared = {**KEYPAD, "meta": {"pattern": "dashboard"}}
    rules = [f["rule"] for f in dashboard_findings("/", declared, {"entities": []})]
    assert "dashboard_no_kpis" in rules


def test_the_floor_reports_a_tool_that_cannot_work_once():
    """Two readings of standalone — a declared pattern, and no pattern with no
    entity — must not report the same fault twice."""
    inert = {"meta": {"pattern": "tool"},
             "root": {"type": "Stack", "children": [
                 {"type": "Button", "props": {"label": "7"}}]}}
    contract = {"id": "PAGE-001", "route": "/", "pattern": "tool", "data": {}}
    rules = [f["rule"] for f in
             _floor_findings("tool", "/", inert, {"entities": []}, contract)]
    assert rules.count("tool_has_no_values") == 1
    assert rules.count("tool_controls_are_inert") == 1
