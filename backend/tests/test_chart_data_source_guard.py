"""Tests for chart_data_source_guard — converting hardcoded Chart `data` arrays
into real op:"series" dataSources bound to the chart."""
import json
import os

from services.chart_data_source_guard import guard_chart_data_sources


_REGISTRY = {
    "entities": {
        "Dispatch": {
            "fields": {
                "id": {"type": "uuid"},
                "status": {"type": "varchar"},
                "createdAt": {"type": "timestamp"},
            }
        },
        "MaintenanceOrder": {
            "fields": {
                "id": {"type": "uuid"},
                "priority": {"type": "varchar"},
                "createdAt": {"type": "timestamp"},
            }
        },
    }
}


def _write(tmp_path, schema, registry=_REGISTRY):
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "home.json").write_text(json.dumps(schema))
    (tmp_path / "registry.json").write_text(json.dumps(registry))
    return str(tmp_path)


def _chart(chart_type, xkey, data, series, node_id="c1"):
    return {
        "id": node_id, "type": "Chart",
        "props": {"chartType": chart_type, "xKey": xkey, "data": data, "series": series},
    }


def _read_home(out):
    return json.load(open(os.path.join(out, "src", "schemas", "home.json")))


def test_category_chart_converts_to_series(tmp_path):
    schema = {
        "id": "home", "route": "/",
        "dataSources": [{"name": "orders", "entity": "MaintenanceOrder", "op": "list"}],
        "root": {"type": "Stack", "children": [
            _chart("bar", "priority",
                   [{"priority": "High", "count": 4}, {"priority": "Low", "count": 2}],
                   [{"name": "Orders", "dataKey": "count"}],
                   node_id="maintenance-priority-chart"),
        ]},
    }
    out = _write(tmp_path, schema)
    res = guard_chart_data_sources(out)
    assert res["converted"] == 1
    home = _read_home(out)
    chart = home["root"]["children"][0]
    assert chart["props"]["data"] == "{{maintenanceOrderByPriority}}" or chart["props"]["data"].startswith("{{")
    assert chart["props"]["xKey"] == "label"
    assert chart["props"]["series"][0]["dataKey"] == "value"
    src = next(d for d in home["dataSources"] if d.get("op") == "series")
    assert src["entity"] == "MaintenanceOrder"
    assert src["groupBy"] == "priority"
    assert src["agg"] == {"fn": "count"}
    assert "bucket" not in src  # category chart, no date bucket


def test_time_chart_converts_with_date_bucket(tmp_path):
    schema = {
        "id": "home", "route": "/",
        "dataSources": [{"name": "dispatches", "entity": "Dispatch", "op": "list"}],
        "root": {"type": "Stack", "children": [
            _chart("line", "week",
                   [{"week": "Wk 1", "dispatches": 42}, {"week": "Wk 2", "dispatches": 55}],
                   [{"name": "Dispatches", "dataKey": "dispatches"}],
                   node_id="dispatch-trend-chart"),
        ]},
    }
    out = _write(tmp_path, schema)
    res = guard_chart_data_sources(out)
    assert res["converted"] == 1
    home = _read_home(out)
    src = next(d for d in home["dataSources"] if d.get("op") == "series")
    assert src["entity"] == "Dispatch"
    assert src["groupBy"] == "createdAt"      # real date column, not the fake "week"
    assert src["bucket"] == "week"


def test_already_bound_chart_is_left_alone(tmp_path):
    schema = {
        "id": "home", "route": "/",
        "dataSources": [{"name": "byStatus", "entity": "Dispatch", "op": "series",
                         "groupBy": "status", "agg": {"fn": "count"}}],
        "root": {"type": "Stack", "children": [
            _chart("bar", "label", "{{byStatus}}", [{"name": "Count", "dataKey": "value"}]),
        ]},
    }
    out = _write(tmp_path, schema)
    res = guard_chart_data_sources(out)
    assert res["converted"] == 0


def test_unmappable_chart_is_skipped_not_broken(tmp_path):
    # xKey "quux" matches no column and isn't date-ish; entity has no category hint col.
    schema = {
        "id": "home", "route": "/",
        "dataSources": [{"name": "d", "entity": "Dispatch", "op": "list"}],
        "root": {"type": "Stack", "children": [
            _chart("bar", "quux",
                   [{"quux": "a", "n": 1}], [{"name": "N", "dataKey": "n"}], node_id="mystery"),
        ]},
    }
    # Give Dispatch no category-hint / matching columns for this test.
    reg = {"entities": {"Dispatch": {"fields": {"id": {"type": "uuid"}}}}}
    out = _write(tmp_path, schema, registry=reg)
    res = guard_chart_data_sources(out)
    assert res["converted"] == 0
    assert res["skipped"] == 1
    home = _read_home(out)
    # Data left as the original literal array — never a broken binding.
    assert isinstance(home["root"]["children"][0]["props"]["data"], list)


def test_idempotent(tmp_path):
    schema = {
        "id": "home", "route": "/",
        "dataSources": [{"name": "orders", "entity": "MaintenanceOrder", "op": "list"}],
        "root": {"type": "Stack", "children": [
            _chart("bar", "priority",
                   [{"priority": "High", "count": 4}], [{"name": "Orders", "dataKey": "count"}],
                   node_id="mp"),
        ]},
    }
    out = _write(tmp_path, schema)
    guard_chart_data_sources(out)
    res2 = guard_chart_data_sources(out)
    assert res2["converted"] == 0  # second pass finds nothing to convert
