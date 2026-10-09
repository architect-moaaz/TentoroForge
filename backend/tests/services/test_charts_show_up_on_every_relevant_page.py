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


KPIS = [_w(90, "PAGE-001", "metric"), _w(91, "PAGE-001", "metric"), _w(92, "PAGE-001", "metric")]


def test_a_dashboard_opens_with_its_numbers():
    charts = [_w(1, "PAGE-001", "chart", "line", bucket="month"), _w(2, "PAGE-001", "chart", "donut"),
              _w(3, "PAGE-001", "chart", "bar"), _w(4, "PAGE-002", "chart", "donut")]
    with pytest.raises(InvalidAnalytics) as e:
        check_analytics(_result(charts + KPIS[:1]), DOC)
    assert "PAGE-001 / (dashboard): has 1 metric tile; it opens with at least 3" in str(e.value)
    check_analytics(_result(charts + KPIS), DOC)


def test_a_dashboard_is_rich_not_repeated():
    three_bars = [_w(1, "PAGE-001", "chart", "bar"), _w(2, "PAGE-001", "chart", "bar"), _w(3, "PAGE-001", "chart", "bar"),
                  _w(4, "PAGE-002", "chart", "donut")] + KPIS
    with pytest.raises(InvalidAnalytics) as e:
        check_analytics(_result(three_bars), DOC)
    assert "its 3 charts are all bar; a dashboard reads through at least 2 different marks" in str(e.value)
    assert "no chart over time, though the data has dates" in str(e.value)
    rich = [_w(1, "PAGE-001", "chart", "line", bucket="month"), _w(2, "PAGE-001", "chart", "donut"),
            _w(3, "PAGE-001", "chart", "bar"), _w(4, "PAGE-002", "chart", "donut")] + KPIS
    check_analytics(_result(rich), DOC)


def test_every_widget_is_about_this_application():
    rich = [_w(1, "PAGE-001", "chart", "line", bucket="month"), _w(2, "PAGE-001", "chart", "donut"),
            _w(3, "PAGE-001", "chart", "bar"), _w(4, "PAGE-002", "chart", "donut")] + KPIS
    with pytest.raises(InvalidAnalytics) as e:
        check_analytics(_result(rich + [_w(5, "PAGE-001", "metric", req=()), _w(6, "PAGE-001", "metric", req=("REQ-404",))]), DOC)
    assert "W5 (w5): names no requirement it answers" in str(e.value)
    assert "W6 (w6): cites REQ-404, which this application does not have" in str(e.value)
    # A Blueprint with no requirements section (a hand-authored one) is not held to citations.
    bare = {k: v for k, v in DOC.items() if k != "requirements"}
    check_analytics(_result(rich + [_w(5, "PAGE-001", "metric", req=())]), bare)


def test_enough_charts_pass_and_nothing_else_is_judged():
    check_analytics(_result([_w(1, "PAGE-001", "chart", "line", bucket="month"), _w(2, "PAGE-001", "chart", "donut"),
                             _w(3, "PAGE-001", "chart", "bar"), _w(4, "PAGE-002", "chart", "bar")] + KPIS), DOC)
    check_analytics(_result([]), DOC)                                       # not an analytics reply
    check_analytics(AgentResult(task_id="t", agent="security", confidence=0.9,
                                proposals=[ArtifactProposal(section="permissions", natural_key="p", body={})]), DOC)


def test_what_can_be_charted():
    assert plottable_fields(DOC["data"]["entities"][0]) == ["status (enum)", "price (number)", "categoryId (reference)", "createdAt (date)"]
    assert plottable_fields(DOC["data"]["entities"][1]) == []
    assert CHARTS_REQUIRED["dashboard"] == 3 and CHARTS_REQUIRED["entity_list"] == 1 and "form" not in CHARTS_REQUIRED


def test_the_author_is_told_the_rule():
    task = NODE_TASKS["analytics"]
    assert "CHARTS SHOW UP ON EVERY RELEVANT STAFF PAGE" in task and "at least three" in task and "`approval_inbox`" in task
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


def test_a_refusal_reaches_the_retry_whole():
    from services.blueprint.orchestrator import ATTEMPTS_BY_NODE, REASON_KEPT, _reason
    problems = "; ".join(f"PAGE-{i:03} /p{i} (entity_list) has 0 charts; it needs at least 1 — a breakdown or a trend "
                         f"over Thing: status (enum), createdAt (date)" for i in range(1, 9))
    kept = _reason(InvalidAnalytics(problems))
    assert "PAGE-008" in kept and len(kept) > 400, "the third page it was failed for was in the message it never saw"
    assert REASON_KEPT >= 4000 and ATTEMPTS_BY_NODE["analytics"] == 3


def test_a_page_for_the_products_customers_is_not_made_to_carry_charts():
    """F&B's customer menu carried a "Price range" chart because every list
    page had to (2026-10-02)."""
    from services.blueprint.agent_contract import customer_facing
    doc = {"roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Customer"}],
           "security": {"signupRole": "ROLE-002"}}
    assert customer_facing(doc, {"access": "public", "users": ["ROLE-001"]})
    assert customer_facing(doc, {"users": ["ROLE-002"]})
    assert not customer_facing(doc, {"users": ["ROLE-001"]})
    assert not customer_facing(doc, {"users": ["ROLE-001", "ROLE-002"]})
    single = {"roles": [{"id": "ROLE-001", "name": "Recruiter"}]}
    assert not customer_facing(single, {"users": ["ROLE-001"]})     # one role: the staff's own tool
    menu = {**DOC, "roles": doc["roles"], "security": doc["security"],
            "pages": [{**p, "access": "public"} for p in DOC["pages"]]}
    check_analytics(_result(KPIS[:1]), menu)                        # nothing forced on a public page


def test_every_page_is_held_to_this_applications_own_bar():
    from services.blueprint.page_review import reviewer_system
    from services.blueprint.ui_engineer import bar, system_prompt
    doc = {"application": {"name": "F&B"}, "designSystem": {"references": [
        {"product": "Deliveroo", "takeaway": "photo-led menu cards"}]}}
    assert "Deliveroo (photo-led menu cards)" in bar(doc)
    for prompt in (system_prompt(doc), reviewer_system(doc)):
        assert "Deliveroo" in prompt and "Linear, Stripe" not in prompt
    assert "own field" in bar({"designSystem": {}})


def test_the_design_director_sees_the_design_and_the_references():
    """The director read `density` and `personality`, keys the design system
    never had, and was told to match "Linear, Stripe or Notion"."""
    from services.blueprint.ui_engineer import direction_prompts
    doc = {"application": {"name": "F&B"}, "pages": [], "roles": [],
           "designSystem": {"visualPersonality": "warm street-food stall", "informationDensity": "comfortable",
                            "shell": {"chrome": "topbar"},
                            "references": [{"product": "Zomato", "takeaway": "photo-led rows"}]}}
    system, user = direction_prompts(doc)
    assert "Linear" not in system + user and "Zomato" in system
    assert "warm street-food stall" in user and "topbar" in user and "LAYOUT patterns" in user
    assert "Zomato: photo-led rows" in user


def test_a_change_is_judged_on_the_pages_it_changes_counted_with_what_is_there():
    """TStyle (forge-v3, 2026-10-09): Smith's rewrites of /trends, / and
    /water-intake were refused one after another — counted from the rewrite's
    own widgets alone, every other page read as chartless."""
    import copy
    full = [_w(1, "PAGE-001", "chart", "line", bucket="month"), _w(2, "PAGE-001", "chart", "donut"),
            _w(3, "PAGE-001", "chart", "bar")] + KPIS
    doc = copy.deepcopy(DOC)
    doc["widgets"] = full                      # /products still has none: an older fault, not this change's
    # A change to the dashboard alone, keeping its charts, is not refused for /products.
    check_analytics(_result([dict(_w(2, "PAGE-001", "chart", "bar"), label="renamed")]), doc)
    # A change that takes the dashboard below its bar is still refused — counted with what stays.
    with pytest.raises(InvalidAnalytics, match="PAGE-001 / \\(dashboard\\) has 2 charts"):
        check_analytics(_result([dict(_w(3, "PAGE-001", "chart", "bar"), status="DEPRECATED", page="PAGE-009")]), doc)
    # A change to /products is judged on /products.
    with pytest.raises(InvalidAnalytics, match="PAGE-002 /products"):
        check_analytics(_result([_w(5, "PAGE-002", "metric")]), doc)
    # The first authoring is still judged on the whole application.
    with pytest.raises(InvalidAnalytics, match="PAGE-002 /products"):
        check_analytics(_result(full), DOC)
