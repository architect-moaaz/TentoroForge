# backend/tests/services/test_aggregate_spec.py
from services.aggregate_spec import (
    find_aggregate_bindings,
    synthesise_metric,
    reconcile_aggregate_specs,
    reconcile_page_file,
)


# ---------------------------------------------------------------------------
# Task 1: find_aggregate_bindings
# ---------------------------------------------------------------------------

def test_finds_metrictile_bindings_to_aggregate_sources():
    page = {
        "dataSources": [
            {"name": "dashboardStats", "entity": "Appointment", "op": "aggregate"},
            {"name": "recent", "entity": "Appointment", "op": "list"},
        ],
        "root": {"children": [
            {"type": "MetricTile", "props": {"value": "{{dashboardStats.todayCount}}"}},
            {"type": "MetricTile", "props": {"value": "{{dashboardStats.monthlyRevenue}}"}},
            {"type": "DataGrid", "props": {"rows": "{{recent}}"}},  # not aggregate
        ]},
    }
    # → {source_name: set(field_names)}
    assert find_aggregate_bindings(page) == {"dashboardStats": {"todayCount", "monthlyRevenue"}}


# ---------------------------------------------------------------------------
# Task 2: synthesise_metric
# ---------------------------------------------------------------------------

def test_synthesise_count_default():
    assert synthesise_metric("activeCount", "Pet", {"Pet": {"createdAt"}}) == {"fn": "count", "entity": "Pet"}


def test_synthesise_today_window():
    m = synthesise_metric("todayCount", "Appointment", {"Appointment": {"date", "createdAt"}})
    assert m["fn"] == "count" and m["window"] == "today"


def test_synthesise_sum_revenue_when_field_exists():
    m = synthesise_metric("monthlyRevenue", "Invoice", {"Invoice": {"total", "createdAt"}})
    assert m["fn"] == "sum" and m["field"] == "total" and m["window"] == "month"


def test_synthesise_falls_back_to_count_when_sum_field_absent():
    # "revenue" implies sum, but no total/amount column → safe count, never an uncomputable metric
    m = synthesise_metric("monthlyRevenue", "Invoice", {"Invoice": {"createdAt"}})
    assert m["fn"] == "count"


# ---------------------------------------------------------------------------
# Task 3: reconcile_aggregate_specs
# ---------------------------------------------------------------------------

def _registry():
    return {"entities": {
        "Appointment": {"fields": [{"name": "date"}, {"name": "createdAt"}]},
        "Invoice": {"fields": [{"name": "total"}, {"name": "status"}, {"name": "createdAt"}]},
    }}


def test_fills_missing_metrics_for_every_binding():
    page = {
        "dataSources": [{"name": "dashboardStats", "entity": "Appointment", "op": "aggregate"}],
        "root": {"children": [
            {"type": "MetricTile", "props": {"value": "{{dashboardStats.todayCount}}"}},
            {"type": "MetricTile", "props": {"value": "{{dashboardStats.monthlyRevenue}}"}},
        ]},
    }
    out, report = reconcile_aggregate_specs(page, _registry())
    ds = next(d for d in out["dataSources"] if d["name"] == "dashboardStats")
    assert set(ds["metrics"].keys()) == {"todayCount", "monthlyRevenue"}
    assert ds["metrics"]["todayCount"]["fn"] == "count"
    assert report["synthesised"] == 2


def test_preserves_agent_supplied_metrics_and_validates_field():
    page = {
        "dataSources": [{
            "name": "dashboardStats", "entity": "Appointment", "op": "aggregate",
            "metrics": {
                "monthlyRevenue": {"fn": "sum", "field": "total", "entity": "Invoice", "window": "month"},
                "bogus": {"fn": "sum", "field": "nonexistent", "entity": "Invoice"},  # invalid → demote to count
            },
        }],
        "root": {"children": [
            {"type": "MetricTile", "props": {"value": "{{dashboardStats.monthlyRevenue}}"}},
        ]},
    }
    out, report = reconcile_aggregate_specs(page, _registry())
    metrics = out["dataSources"][0]["metrics"]
    assert metrics["monthlyRevenue"] == {"fn": "sum", "field": "total", "entity": "Invoice", "window": "month"}
    assert metrics["bogus"]["fn"] == "count"  # invalid sum field demoted
    assert report["demoted"] == 1


# ---------------------------------------------------------------------------
# Task 4: reconcile_page_file
# ---------------------------------------------------------------------------

import json


def test_reconcile_page_file_rewrites_schema(tmp_path):
    page = {
        "dataSources": [{"name": "dashboardStats", "entity": "Appointment", "op": "aggregate"}],
        "root": {"children": [{"type": "MetricTile", "props": {"value": "{{dashboardStats.todayCount}}"}}]},
    }
    fp = tmp_path / "analytics.json"
    fp.write_text(json.dumps(page))
    registry = {"entities": {"Appointment": {"fields": [{"name": "createdAt"}]}}}
    report = reconcile_page_file(fp, registry)
    out = json.loads(fp.read_text())
    assert out["dataSources"][0]["metrics"]["todayCount"]["fn"] == "count"
    assert report["synthesised"] == 1


def test_entity_fields_tolerates_real_registry_shapes():
    """registry.json stores fields as a dict {name: {...}}; older shapes use a list
    of {name} dicts or plain strings. _entity_fields must handle all three (a real
    4sashx7f registry crashed the dict path)."""
    from services.aggregate_spec import _entity_fields
    reg = {"entities": {
        "Dictish":  {"fields": {"id": {"type": "uuid"}, "total": {"type": "int"}}},
        "Listish":  {"fields": [{"name": "id"}, {"name": "amount"}]},
        "Stringish": {"fields": ["id", "qty"]},
        "Bogus":    "not-a-dict",
    }}
    out = _entity_fields(reg)
    assert out["Dictish"] == {"id", "total"}
    assert out["Listish"] == {"id", "amount"}
    assert out["Stringish"] == {"id", "qty"}
    assert "Bogus" not in out


def test_reconcile_with_dict_shaped_fields_demotes_correctly():
    from services.aggregate_spec import reconcile_aggregate_specs
    page = {
        "dataSources": [{"name": "s", "entity": "Invoice", "op": "aggregate",
                         "metrics": {"rev": {"fn": "sum", "field": "total"},
                                     "bad": {"fn": "sum", "field": "ghost"}}}],
        "root": {"children": [{"type": "MetricTile", "props": {"value": "{{s.rev}}"}}]},
    }
    reg = {"entities": {"Invoice": {"fields": {"total": {"type": "int"}, "createdAt": {}}}}}
    out, report = reconcile_aggregate_specs(page, reg)
    m = out["dataSources"][0]["metrics"]
    assert m["rev"] == {"fn": "sum", "field": "total", "entity": "Invoice"}  # valid kept
    assert m["bad"]["fn"] == "count"  # ghost field demoted


def test_stats_op_is_treated_as_aggregate_and_normalised():
    """The page agent uses BOTH op:'aggregate' and op:'stats' for KPI sources. The floor
    must floor 'stats' sources too AND normalise them to 'aggregate' so the runtime
    resolver (which only branches on 'aggregate') computes them."""
    from services.aggregate_spec import reconcile_aggregate_specs, find_aggregate_bindings
    page = {
        "dataSources": [{"name": "invoiceStats", "entity": "Invoice", "op": "stats"}],
        "root": {"children": [
            {"type": "MetricTile", "props": {"value": "{{invoiceStats.totalRevenue}}"}},
            {"type": "MetricTile", "props": {"value": "{{invoiceStats.paidCount}}"}},
        ]},
    }
    assert find_aggregate_bindings(page) == {"invoiceStats": {"totalRevenue", "paidCount"}}
    reg = {"entities": {"Invoice": {"fields": {"total": {}, "createdAt": {}}}}}
    out, report = reconcile_aggregate_specs(page, reg)
    ds = out["dataSources"][0]
    assert ds["op"] == "aggregate"              # normalised
    assert report["normalised"] == 1
    assert set(ds["metrics"].keys()) == {"totalRevenue", "paidCount"}


# ---------------------------------------------------------------------------
# ratio / period-delta metrics survive reconciliation (not clobbered to count)
# ---------------------------------------------------------------------------

def _reg():
    return {"entities": {"Request": {"fields": {"status": {}, "createdAt": {}, "cost": {}}}}}


def test_ratio_metric_passes_through_reconcile():
    page = {"dataSources": [{
        "name": "stats", "entity": "Request", "op": "aggregate",
        "metrics": {"hitRate": {
            "kind": "ratio", "percent": True,
            "numerator": {"fn": "count", "filter": {"status": "hit"}},
            "denominator": {"fn": "count"},
        }},
    }], "root": {"children": []}}
    out, _ = reconcile_aggregate_specs(page, _reg())
    m = out["dataSources"][0]["metrics"]["hitRate"]
    assert m["kind"] == "ratio" and m["percent"] is True
    assert m["numerator"]["filter"] == {"status": "hit"}
    assert m["denominator"]["fn"] == "count"


def test_delta_metric_keeps_kind_and_window():
    page = {"dataSources": [{
        "name": "stats", "entity": "Request", "op": "aggregate",
        "metrics": {"spendDelta": {
            "kind": "delta", "fn": "sum", "field": "cost", "window": "month", "percent": True,
        }},
    }], "root": {"children": []}}
    out, _ = reconcile_aggregate_specs(page, _reg())
    m = out["dataSources"][0]["metrics"]["spendDelta"]
    assert m["kind"] == "delta" and m["window"] == "month" and m["percent"] is True
    assert m["fn"] == "sum" and m["field"] == "cost"


def test_delta_demotes_bad_field_but_stays_delta():
    page = {"dataSources": [{
        "name": "stats", "entity": "Request", "op": "aggregate",
        "metrics": {"d": {"kind": "delta", "fn": "sum", "field": "ghostCol", "window": "week"}},
    }], "root": {"children": []}}
    out, rep = reconcile_aggregate_specs(page, _reg())
    m = out["dataSources"][0]["metrics"]["d"]
    assert m["kind"] == "delta" and m["window"] == "week"   # kind + window preserved
    assert m["fn"] == "count"                                # bad field demoted to count
    assert rep["demoted"] == 1
