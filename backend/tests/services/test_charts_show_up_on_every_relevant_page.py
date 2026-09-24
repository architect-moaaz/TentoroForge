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


def _w(i, page, kind, mark=None, bucket=None, req=("REQ-001",)):
    w = {"id": f"W{i}", "page": page, "kind": kind, "label": f"w{i}", "requirements": list(req),
         "dataSource": {"op": "query", "entity": "ENTITY-001", "measures": [{"fn": "count", "key": "n"}],
                        "dimensions": [{"field": "createdAt", "bucket": bucket}] if bucket else []}}
    if mark:
        w["chart"] = {"mark": mark}
    return w


DOC["requirements"] = [{"id": "REQ-001", "statement": "See how things stand"}]


def test_a_dashboard_and_a_list_over_chartable_records_must_carry_charts():
    with pytest.raises(InvalidAnalytics) as e:
        check_analytics(_result([_w(1, "PAGE-001", "metric"), _w(2, "PAGE-001", "chart", "bar"),
                                 _w(3, "PAGE-002", "metric")]), DOC)
    msg = str(e.value)
    assert "PAGE-001 / (dashboard) has 1 chart; it needs at least 3" in msg
    assert "PAGE-002 /products (entity_list) has 0 charts; it needs at least 1" in msg
    assert "over Product: status (enum), price (number), categoryId (reference), createdAt (date)" in msg
    assert "PAGE-003" not in msg, "a list of free text has nothing to chart"
    assert "PAGE-004" not in msg, "a form carries none"
    assert "PAGE-005" not in msg, "a retired page is not a page"


def test_a_dashboard_is_rich_not_repeated():
    three_bars = [_w(1, "PAGE-001", "chart", "bar"), _w(2, "PAGE-001", "chart", "bar"), _w(3, "PAGE-001", "chart", "bar"),
                  _w(4, "PAGE-002", "chart", "donut")]
    with pytest.raises(InvalidAnalytics) as e:
        check_analytics(_result(three_bars), DOC)
    assert "its 3 charts are all bar; a dashboard reads through at least 2 different marks" in str(e.value)
    assert "no chart over time, though the data has dates" in str(e.value)
    rich = [_w(1, "PAGE-001", "chart", "line", bucket="month"), _w(2, "PAGE-001", "chart", "donut"),
            _w(3, "PAGE-001", "chart", "bar"), _w(4, "PAGE-002", "chart", "donut")]
    check_analytics(_result(rich), DOC)


def test_every_widget_is_about_this_application():
    rich = [_w(1, "PAGE-001", "chart", "line", bucket="month"), _w(2, "PAGE-001", "chart", "donut"),
            _w(3, "PAGE-001", "chart", "bar"), _w(4, "PAGE-002", "chart", "donut")]
    with pytest.raises(InvalidAnalytics) as e:
        check_analytics(_result(rich + [_w(5, "PAGE-001", "metric", req=()), _w(6, "PAGE-001", "metric", req=("REQ-404",))]), DOC)
    assert "W5 (w5): names no requirement it answers" in str(e.value)
    assert "W6 (w6): cites REQ-404, which this application does not have" in str(e.value)
    # A Blueprint with no requirements section (a hand-authored one) is not held to citations.
    bare = {k: v for k, v in DOC.items() if k != "requirements"}
    check_analytics(_result(rich + [_w(5, "PAGE-001", "metric", req=())]), bare)


def test_enough_charts_pass_and_nothing_else_is_judged():
    check_analytics(_result([_w(1, "PAGE-001", "chart", "line", bucket="month"), _w(2, "PAGE-001", "chart", "donut"),
                             _w(3, "PAGE-001", "chart", "bar"), _w(4, "PAGE-002", "chart", "bar")]), DOC)
    check_analytics(_result([]), DOC)                                       # not an analytics reply
    check_analytics(AgentResult(task_id="t", agent="security", confidence=0.9,
                                proposals=[ArtifactProposal(section="permissions", natural_key="p", body={})]), DOC)


def test_what_can_be_charted():
    assert plottable_fields(DOC["data"]["entities"][0]) == ["status (enum)", "price (number)", "categoryId (reference)", "createdAt (date)"]
    assert plottable_fields(DOC["data"]["entities"][1]) == []
    assert CHARTS_REQUIRED["dashboard"] == 3 and CHARTS_REQUIRED["entity_list"] == 1 and "form" not in CHARTS_REQUIRED


def test_the_author_is_told_the_rule():
    task = NODE_TASKS["analytics"]
    assert "CHARTS SHOW UP ON EVERY RELEVANT PAGE" in task and "at least three" in task and "`approval_inbox`" in task
    assert "A DASHBOARD IS RICH" in task and "`timeField`" in task and "Never a generic" in task


ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


def test_a_metric_read_over_a_range_carries_its_change_against_the_period_before():
    sdk = (ROOT / "templates/app-foundation/src/sdk/server.ts").read_text()
    assert "previous?: number | null;" in sdk and "delta?: number | null;" in sdk
    assert "function previousRange(range: DateRange)" in sdk and "`${widget.id}:previous`" in sdk
    view = (ROOT / "templates/app-foundation/src/sdk/widget-view.tsx").read_text()
    assert 'direction: delta >= 0 ? "up" : "down"' in view
    shim = (ROOT / "static/jit-samples.mjs").read_text()
    assert "previous?: number | null; delta?: number | null" in shim and "delta: (value - previous) / previous" in shim
    from services.blueprint.ui_engineer import SDK_GUIDE
    assert "delta?: number | null" in SDK_GUIDE
