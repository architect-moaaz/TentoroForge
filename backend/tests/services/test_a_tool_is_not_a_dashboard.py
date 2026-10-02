"""A page with nothing to summarise is not held to a dashboard's floor.

A single-page calculator was declined three times, at ~135 seconds a
composition, for having no KPI tiles, no chart and no recent-activity surface
— on an application whose requirements say it stores nothing at all. The floor
decided what the page must contain from its ROUTE ("/" is always a dashboard),
and a route says nothing about what a page is for.

The floor's three demands each count, plot or list RECORDS, and the composer is
separately forbidden from writing a number it cannot bind. A page with no data
source cannot satisfy both rules, so it fails for ever.
"""

from __future__ import annotations

from services.a2ui_authority import _floor_findings, _summarises_something

_CALCULATOR = {
    "root": {"type": "Stack", "props": {}, "children": [
        {"type": "Text", "props": {"content": "0"}, "children": []},
        {"type": "Button", "props": {"label": "7"}, "children": []},
        {"type": "Button", "props": {"label": "="}, "children": []}]},
}

_DASHBOARD = {
    "dataSources": [{"name": "nurses", "entity": "Nurse", "op": "list"}],
    "root": {"type": "Stack", "props": {}, "children": [
        {"type": "Text", "props": {"content": "{{nurses.count}}"}, "children": []}]},
}


_TOOL_CONTRACT = {"id": "PAGE-001", "route": "/", "pattern": "dashboard"}
_RECORD_CONTRACT = {"id": "PAGE-002", "route": "/", "pattern": "dashboard",
                    "data": {"primaryEntity": "ENTITY-001"}}


def test_the_page_contract_says_whether_there_is_anything_to_summarise():
    assert _summarises_something(_CALCULATOR, _TOOL_CONTRACT) is False
    assert _summarises_something(_DASHBOARD, _RECORD_CONTRACT) is True
    # A contract that names no entity, over a composition that bound data
    # anyway: the page does summarise something, so the floor judges it.
    assert _summarises_something(_DASHBOARD, _TOOL_CONTRACT) is True
    # NO CONTRACT TO READ: judged exactly as before, or a composer that
    # forgot to bind its sources would ship a blank dashboard.
    assert _summarises_something(_CALCULATOR, None) is True


def test_a_tool_at_the_root_is_not_asked_for_kpis_it_cannot_have():
    rules = {f["rule"] for f in _floor_findings("dashboard", "/", _CALCULATOR, {},
                                                _TOOL_CONTRACT)}
    assert not any(r.startswith("dashboard_") for r in rules), sorted(rules)


def test_a_real_dashboard_is_still_held_to_the_floor():
    """The floor is not weakened — a page that DOES summarise records is
    judged exactly as before, or a broken dashboard would sail through."""
    rules = {f["rule"] for f in _floor_findings("dashboard", "/", _DASHBOARD, {},
                                                _RECORD_CONTRACT)}
    assert "dashboard_no_kpis" in rules
    assert "dashboard_no_chart" in rules
    assert "dashboard_no_activity" in rules


def test_a_binding_with_no_source_is_still_caught_either_way():
    """The dangling-binding check is not part of the floor and must survive:
    it is what catches four stat tiles reading four invented sources."""
    phantom = {"root": {"type": "Stat", "props": {"label": "x",
                                                  "value": "{{overdue.value}}"},
                        "children": []}}
    rules = [f["rule"] for f in _floor_findings("dashboard", "/", phantom, {},
                                                _TOOL_CONTRACT)]
    assert any("has no declared data source" in r for r in rules)
