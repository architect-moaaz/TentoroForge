"""Tests for fixtures.enum_enrich — distributing expected enum values into
editor-preview fixtures so KPI filters match and chart buckets populate."""
import json

from services.fixtures.enum_enrich import (
    harvest_value_pools,
    enrich_records,
    enrich_preview_data,
)


def _write_schema(tmp_path, schema):
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "home.json").write_text(json.dumps(schema))
    return str(sdir)


_SCHEMA = {
    "id": "home", "route": "/",
    "dataSources": [
        {
            "name": "stats", "entity": "Vehicle", "op": "aggregate",
            "metrics": {
                "active": {"fn": "count", "entity": "Dispatch", "filter": {"status": "active"}},
                "done": {"fn": "count", "entity": "Dispatch", "filter": {"status": "completed"}},
                "crit": {"fn": "count", "entity": "MaintenanceOrder", "filter": {"priority": "critical"}},
            },
        },
        {"name": "byPriority", "entity": "MaintenanceOrder", "op": "series", "groupBy": "priority"},
        {"name": "byWeek", "entity": "Dispatch", "op": "series", "groupBy": "createdAt", "bucket": "week"},
    ],
}


def test_harvest_includes_filter_values_first_then_defaults(tmp_path):
    pools = harvest_value_pools(_write_schema(tmp_path, _SCHEMA))
    # Dispatch.status filter values come first, guaranteeing they appear.
    assert pools["Dispatch"]["status"][:2] == ["active", "completed"]
    assert "pending" in pools["Dispatch"]["status"]  # default variety merged in
    # MaintenanceOrder.priority: "critical" (filter) first, plus low/medium/high.
    assert pools["MaintenanceOrder"]["priority"][0] == "critical"
    assert set(["low", "medium", "high"]).issubset(set(pools["MaintenanceOrder"]["priority"]))


def test_harvest_skips_date_groupby(tmp_path):
    pools = harvest_value_pools(_write_schema(tmp_path, _SCHEMA))
    # createdAt is a date series groupBy → never enum-filled.
    assert "createdAt" not in pools.get("Dispatch", {})


def test_enrich_distributes_and_matches_filters(tmp_path):
    pools = harvest_value_pools(_write_schema(tmp_path, _SCHEMA))
    data = {
        "Dispatch": [{"id": str(i)} for i in range(8)],
        "MaintenanceOrder": [{"id": str(i)} for i in range(8)],
    }
    filled = enrich_records(data, pools)
    assert filled >= 2
    statuses = [r["status"] for r in data["Dispatch"]]
    # Every filtered value is present at least once → KPI counts are non-zero.
    assert "active" in statuses and "completed" in statuses
    # Chart groupBy gets multiple buckets.
    assert len({r["priority"] for r in data["MaintenanceOrder"]}) >= 3


def test_enrich_shared_alias_lists_once(tmp_path):
    pools = harvest_value_pools(_write_schema(tmp_path, _SCHEMA))
    shared = [{"id": "1"}, {"id": "2"}]
    data = {"Dispatch": shared, "dispatch": shared, "dispatchs": shared}
    enrich_records(data, pools)
    # All aliases reflect the same enriched list, and status was set once.
    assert data["dispatch"][0].get("status") in pools["Dispatch"]["status"]
    assert data["Dispatch"] is data["dispatch"]


def test_enrich_preview_data_end_to_end(tmp_path):
    sdir = _write_schema(tmp_path, _SCHEMA)
    data = {"MaintenanceOrder": [{"id": str(i)} for i in range(6)]}
    n = enrich_preview_data(data, sdir)
    assert n >= 1
    assert all("priority" in r for r in data["MaintenanceOrder"])


def test_no_schemas_dir_is_safe():
    assert harvest_value_pools("/nonexistent/dir") == {}
    assert enrich_records({}, {}) == 0
