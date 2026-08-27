"""Tests for the planner-authored dashboard widgets + deterministic dashboard builder.

Covers:
  * build_dashboard_page renders stat/chart/table widgets into real aggregate/series/list
    dataSources (reusing the runtime shapes) + bound MetricTile/Chart/Table nodes.
  * a widget naming a non-existent entity/column is DROPPED, others kept.
  * no widgets → None (LLM fallback preserved).
  * _sanitize_page_widgets keeps well-formed widgets, drops malformed ones.
  * schema_pipeline._emit_deterministic_page routes a report page WITH widgets through the
    deterministic builder (no LLM call).

Run: cd backend && /usr/local/bin/python3 -m pytest tests/test_dashboard_builder.py -v
"""
from __future__ import annotations

import json
import os

from services.deterministic_pages import build_dashboard_page


# ── registry fixture ────────────────────────────────────────────────────────
def _registry() -> dict:
    """{EntityName: {fields: {col: {type}}}} — the shape the plan/registry carry."""
    return {
        "Rental": {"fields": {
            "id": {"type": "uuid"},
            "status": {"type": "varchar"},
            "createdAt": {"type": "timestamp"},
            "customerId": {"type": "uuid"},
        }},
        "Payment": {"fields": {
            "id": {"type": "uuid"},
            "amount": {"type": "numeric"},
            "method": {"type": "varchar"},
        }},
    }


def _nodes(page: dict) -> list[dict]:
    """Flatten every node in the page tree."""
    out: list[dict] = []

    def walk(n):
        if isinstance(n, dict):
            if "type" in n:
                out.append(n)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)

    walk(page.get("root"))
    return out


def _ds_by_op(page: dict, op: str) -> list[dict]:
    return [d for d in page.get("dataSources", []) if d.get("op") == op]


# ── 1. full dashboard: stat count, stat sum, chart groupBy, table limit ──────
def test_build_dashboard_page_full():
    page = {
        "name": "AnalyticsPage",
        "route": "/analytics",
        "type": "dashboard",
        "archetype": "report",
        "widgets": [
            {"type": "stat", "entity": "Rental", "metric": {"fn": "count"}, "title": "Total Rentals"},
            {"type": "stat", "entity": "Payment", "metric": {"fn": "sum", "field": "amount"}, "title": "Revenue"},
            {"type": "chart", "entity": "Rental", "groupBy": "status", "title": "By Status"},
            {"type": "table", "entity": "Rental", "limit": 5, "columns": ["status"], "title": "Recent"},
        ],
    }
    dash = build_dashboard_page(page, _registry())
    assert dash is not None
    assert dash["schemaVersion"] == "2"
    assert dash["route"] == "/analytics"

    # aggregate dataSources (one count on Rental, one sum(amount) on Payment)
    aggs = _ds_by_op(dash, "aggregate")
    assert len(aggs) == 2
    count_agg = next(a for a in aggs if a["entity"] == "Rental")
    assert count_agg["metrics"]["value"] == {"fn": "count"}
    sum_agg = next(a for a in aggs if a["entity"] == "Payment")
    assert sum_agg["metrics"]["value"] == {"fn": "sum", "field": "amount"}

    # series dataSource for the chart
    series = _ds_by_op(dash, "series")
    assert len(series) == 1
    assert series[0]["entity"] == "Rental"
    assert series[0]["groupBy"] == "status"
    assert series[0]["op"] == "series"

    # list dataSource for the table
    lists = _ds_by_op(dash, "list")
    assert len(lists) == 1
    assert lists[0]["entity"] == "Rental"
    assert lists[0]["limit"] == 5

    # nodes bound to the dataSources
    nodes = _nodes(dash)
    tiles = [n for n in nodes if n["type"] == "MetricTile"]
    assert len(tiles) == 2
    for t in tiles:
        assert t["props"]["value"] == "{{%s.value}}" % _agg_for(dash, t)

    charts = [n for n in nodes if n["type"] == "Chart"]
    assert len(charts) == 1
    assert charts[0]["props"]["data"] == "{{%s}}" % series[0]["name"]
    assert charts[0]["props"]["xKey"] == "label"
    assert charts[0]["props"]["series"] == [{"name": "By Status", "dataKey": "value"}]

    tables = [n for n in nodes if n["type"] == "Table"]
    assert len(tables) == 1
    assert tables[0]["props"]["rows"] == "{{%s}}" % lists[0]["name"]


def _agg_for(dash: dict, tile: dict) -> str:
    """The aggregate dataSource name the tile's value binding points at."""
    binding = tile["props"]["value"]  # "{{name.value}}"
    return binding[2:-len(".value}}")]


# ── 2. widget referencing a non-existent entity/column → dropped ─────────────
def test_invalid_entity_and_column_dropped():
    page = {
        "name": "Dash",
        "route": "/dash",
        "widgets": [
            {"type": "stat", "entity": "Ghost", "metric": {"fn": "count"}},        # bad entity
            {"type": "chart", "entity": "Rental", "groupBy": "nonexistent"},        # bad column
            {"type": "stat", "entity": "Payment", "metric": {"fn": "sum", "field": "nope"}},  # bad field
            {"type": "stat", "entity": "Rental", "metric": {"fn": "count"}, "title": "Good"},  # valid
        ],
    }
    dash = build_dashboard_page(page, _registry())
    assert dash is not None
    # only the one valid stat survives
    assert len(dash["dataSources"]) == 1
    assert dash["dataSources"][0]["entity"] == "Rental"
    assert dash["dataSources"][0]["op"] == "aggregate"
    tiles = [n for n in _nodes(dash) if n["type"] == "MetricTile"]
    assert len(tiles) == 1
    assert tiles[0]["props"]["label"] == "Good"


def test_bad_filter_column_drops_widget():
    page = {
        "route": "/dash",
        "widgets": [
            {"type": "table", "entity": "Rental", "filter": {"ghostCol": "x"}},   # bad filter col
            {"type": "table", "entity": "Rental", "filter": {"status": "active"}},  # valid filter col
        ],
    }
    dash = build_dashboard_page(page, _registry())
    assert dash is not None
    lists = _ds_by_op(dash, "list")
    assert len(lists) == 1
    assert lists[0]["filter"] == {"status": "active"}


# ── 3. no widgets → None (LLM fallback) ──────────────────────────────────────
def test_no_widgets_returns_none():
    assert build_dashboard_page({"route": "/x"}, _registry()) is None
    assert build_dashboard_page({"route": "/x", "widgets": []}, _registry()) is None


def test_all_widgets_invalid_returns_none():
    page = {"route": "/x", "widgets": [
        {"type": "stat", "entity": "Ghost", "metric": {"fn": "count"}},
    ]}
    assert build_dashboard_page(page, _registry()) is None


# ── 4. chart with date bucket ────────────────────────────────────────────────
def test_chart_date_bucket():
    page = {"route": "/x", "widgets": [
        {"type": "chart", "entity": "Rental", "groupBy": "createdAt", "bucket": "month", "title": "Trend"},
    ]}
    dash = build_dashboard_page(page, _registry())
    series = _ds_by_op(dash, "series")
    assert len(series) == 1
    assert series[0]["groupBy"] == "createdAt"
    assert series[0]["bucket"] == "month"
    assert series[0]["sort"] == "label"


# ── 5. _sanitize_page_widgets: keep well-formed, drop malformed ──────────────
def test_sanitize_page_widgets():
    from agents.planner import _sanitize_page_widgets

    plan = {"pages": [{
        "route": "/analytics",
        "widgets": [
            {"type": "stat", "entity": "Rental", "metric": {"fn": "count"}, "title": "T"},   # ok
            {"type": "stat", "entity": "Payment", "metric": {"fn": "sum", "field": "amount"}},  # ok
            {"type": "chart", "entity": "Rental", "groupBy": "status", "bucket": "week"},      # ok
            {"type": "table", "entity": "Rental", "limit": 5, "columns": ["status"]},          # ok
            {"type": "stat", "entity": "Rental"},                       # malformed: no metric
            {"type": "stat", "entity": "Payment", "metric": {"fn": "sum"}},  # malformed: sum w/o field
            {"type": "bogus", "entity": "Rental"},                     # malformed: bad type
            {"type": "chart", "entity": "Rental"},                     # malformed: no groupBy
            {"type": "stat"},                                          # malformed: no entity
            "nope",                                                    # malformed: not a dict
        ],
    }]}
    out = _sanitize_page_widgets(plan)
    widgets = out["pages"][0]["widgets"]
    assert len(widgets) == 4
    assert [w["type"] for w in widgets] == ["stat", "stat", "chart", "table"]
    # the sum stat keeps its field; the chart keeps its bucket
    assert widgets[1]["metric"] == {"fn": "sum", "field": "amount"}
    assert widgets[2]["bucket"] == "week"
    assert widgets[3]["limit"] == 5


# ── 6. dispatch: a report page with widgets goes deterministic (no LLM) ──────
def test_dispatch_report_with_widgets_is_deterministic(tmp_path):
    from services.schema_pipeline import _emit_deterministic_page

    output_dir = str(tmp_path)
    os.makedirs(os.path.join(output_dir, "src", "schemas"), exist_ok=True)
    # registry.json so build_dashboard_page can resolve entities (plan has none)
    with open(os.path.join(output_dir, "registry.json"), "w", encoding="utf-8") as fh:
        json.dump({"entities": _registry()}, fh)

    plan = {"entities": _registry()}
    page = {
        "name": "AnalyticsPage",
        "route": "/analytics",
        "type": "dashboard",
        "archetype": "report",
        "widgets": [
            {"type": "stat", "entity": "Rental", "metric": {"fn": "count"}, "title": "Total"},
            {"type": "chart", "entity": "Rental", "groupBy": "status"},
        ],
    }
    handled = _emit_deterministic_page(output_dir, plan, page)
    assert handled is True  # deterministic path took it — no LLM

    written = os.path.join(output_dir, "src", "schemas", "analytics.json")
    assert os.path.exists(written)
    with open(written, encoding="utf-8") as fh:
        schema = json.load(fh)
    ops = sorted(d["op"] for d in schema["dataSources"])
    assert ops == ["aggregate", "series"]


# ── 7. layout + spacing enrichment (Task A-1) ────────────────────────────────
def _grid_children(page: dict, child_type: str) -> list[dict]:
    """The Grid nodes whose direct children include a node of `child_type`."""
    out: list[dict] = []
    for n in _nodes(page):
        if n.get("type") != "Grid":
            continue
        kids = n.get("children") or []
        if any(isinstance(k, dict) and _contains_type(k, child_type) for k in kids):
            out.append(n)
    return out


def _contains_type(node: dict, t: str) -> bool:
    for n in _nodes({"root": node}):
        if n.get("type") == t:
            return True
    return False


def test_dashboard_kpis_in_equal_grid():
    page = {
        "name": "Ops", "route": "/ops",
        "widgets": [
            {"type": "stat", "entity": "Rental", "metric": {"fn": "count"}, "title": "A"},
            {"type": "stat", "entity": "Rental", "metric": {"fn": "count"}, "title": "B"},
            {"type": "stat", "entity": "Payment", "metric": {"fn": "sum", "field": "amount"}, "title": "C"},
        ],
    }
    dash = build_dashboard_page(page, _registry())
    # KPI tiles live in a Grid whose columns == the number of stats (equal-width),
    # NOT a wrap Row.
    kpi_grids = _grid_children(dash, "MetricTile")
    assert len(kpi_grids) == 1
    assert kpi_grids[0]["props"]["columns"] == 3
    assert not any(n.get("type") == "Row" for n in _nodes(dash))


def test_dashboard_charts_in_two_col_grid():
    page = {
        "name": "Ops", "route": "/ops",
        "widgets": [
            {"type": "chart", "entity": "Rental", "groupBy": "status", "title": "By Status"},
            {"type": "table", "entity": "Rental", "limit": 5, "title": "Recent"},
        ],
    }
    dash = build_dashboard_page(page, _registry())
    # ≥2 content widgets → a single 2-col Grid holding both Cards, not stacked full-width.
    two_col = [n for n in _nodes(dash)
               if n.get("type") == "Grid" and n["props"].get("columns") == 2]
    assert len(two_col) == 1
    # both the chart card and the table card are inside it
    assert _contains_type(two_col[0], "Chart")
    assert _contains_type(two_col[0], "Table")


def test_dashboard_uses_semantic_spacing_tokens():
    page = {
        "name": "Ops", "route": "/ops",
        "widgets": [
            {"type": "stat", "entity": "Rental", "metric": {"fn": "count"}, "title": "A"},
            {"type": "chart", "entity": "Rental", "groupBy": "status"},
            {"type": "table", "entity": "Rental", "limit": 5},
        ],
    }
    dash = build_dashboard_page(page, _registry())
    # root Stack uses the semantic section token (not raw tokens.spacing.6)
    assert dash["root"]["props"]["gap"] == "tokens.spacing.semantic.section"
    # every Grid uses the semantic card token
    grids = [n for n in _nodes(dash) if n.get("type") == "Grid"]
    assert grids
    for g in grids:
        assert g["props"]["gap"] == "tokens.spacing.semantic.card"
    # no raw tokens.spacing.6 anywhere in the tree
    import json as _json
    assert "tokens.spacing.6" not in _json.dumps(dash)


def test_dispatch_report_no_widgets_falls_through(tmp_path):
    """A report page WITHOUT widgets is NOT handled deterministically → LLM fallback."""
    from services.schema_pipeline import _emit_deterministic_page

    output_dir = str(tmp_path)
    os.makedirs(os.path.join(output_dir, "src", "schemas"), exist_ok=True)
    with open(os.path.join(output_dir, "registry.json"), "w", encoding="utf-8") as fh:
        json.dump({"entities": _registry()}, fh)

    plan = {"entities": _registry()}
    page = {"name": "AnalyticsPage", "route": "/analytics", "type": "dashboard", "archetype": "report"}
    assert _emit_deterministic_page(output_dir, plan, page) is False
