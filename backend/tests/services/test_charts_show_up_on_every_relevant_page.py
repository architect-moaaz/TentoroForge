"""Charts show up on every relevant page.

The analytics agent decided page by page and decided "none" for a
product's home dashboard and for every list of its catalogue (zo9k0ekd:
0 of 24 widgets on `/`, `/categories`, `/products`); 21bov6l1 shipped no
widget at all. The contract now refuses a reply that leaves a dashboard
without two charts or a list over chartable records without one, naming
the page and the fields it could chart — and the author is told the rule.
"""
import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, CHARTS_REQUIRED, InvalidAnalytics, check_analytics, plottable_fields,
)
from services.blueprint.executors import NODE_TASKS

DOC = {
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Product", "fields": [
            {"name": "name", "type": "string"}, {"name": "status", "type": "string", "enumValues": ["DRAFT", "LIVE"]},
            {"name": "price", "type": "currency"}, {"name": "categoryId", "type": "string", "references": "ENTITY-002"},
            {"name": "createdAt", "type": "datetime"}]},
        {"id": "ENTITY-002", "name": "Category", "fields": [{"name": "name", "type": "string"}, {"name": "notes", "type": "text"}]},
    ]},
    "pages": [
        {"id": "PAGE-001", "route": "/", "pattern": "dashboard"},
        {"id": "PAGE-002", "route": "/products", "pattern": "entity_list", "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-003", "route": "/categories", "pattern": "entity_list", "data": {"primaryEntity": "ENTITY-002"}},
        {"id": "PAGE-004", "route": "/products/new", "pattern": "form", "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-005", "route": "/old", "pattern": "dashboard", "status": "DEPRECATED"},
    ],
}


def _result(widgets):
    return AgentResult(task_id="TASK-analytics", agent="analytics", confidence=0.9,
                       proposals=[ArtifactProposal(section="widgets", natural_key=w["id"], body=w) for w in widgets])


def _w(i, page, kind):
    return {"id": f"W{i}", "page": page, "kind": kind, "label": f"w{i}"}


def test_a_dashboard_and_a_list_over_chartable_records_must_carry_charts():
    with pytest.raises(InvalidAnalytics) as e:
        check_analytics(_result([_w(1, "PAGE-001", "metric"), _w(2, "PAGE-001", "chart"),
                                 _w(3, "PAGE-002", "metric")]), DOC)
    msg = str(e.value)
    assert "PAGE-001 / (dashboard) has 1 chart; it needs at least 2" in msg
    assert "PAGE-002 /products (entity_list) has 0 charts; it needs at least 1" in msg
    assert "over Product: status (enum), price (number), categoryId (reference), createdAt (date)" in msg
    assert "PAGE-003" not in msg, "a list of free text has nothing to chart"
    assert "PAGE-004" not in msg, "a form carries none"
    assert "PAGE-005" not in msg, "a retired page is not a page"


def test_enough_charts_pass_and_nothing_else_is_judged():
    check_analytics(_result([_w(1, "PAGE-001", "chart"), _w(2, "PAGE-001", "chart"), _w(3, "PAGE-002", "chart")]), DOC)
    check_analytics(_result([]), DOC)                                       # not an analytics reply
    check_analytics(AgentResult(task_id="t", agent="security", confidence=0.9,
                                proposals=[ArtifactProposal(section="permissions", natural_key="p", body={})]), DOC)


def test_what_can_be_charted():
    assert plottable_fields(DOC["data"]["entities"][0]) == ["status (enum)", "price (number)", "categoryId (reference)", "createdAt (date)"]
    assert plottable_fields(DOC["data"]["entities"][1]) == []
    assert CHARTS_REQUIRED["dashboard"] == 2 and CHARTS_REQUIRED["entity_list"] == 1 and "form" not in CHARTS_REQUIRED


def test_the_author_is_told_the_rule():
    task = NODE_TASKS["analytics"]
    assert "CHARTS SHOW UP ON EVERY RELEVANT PAGE" in task and "at least two" in task and "`approval_inbox`" in task
