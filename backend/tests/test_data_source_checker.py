"""data_source_checker — the runtime Smith tool built in Slice 12B.

Verifies both the deductive rules (per-op allowed/required keys) and
the resource-registry entity check. The peer-hint path is covered by
peer_shape_analyzer's own tests; here we just confirm the tool returns
what the analyzer produced.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.data_source_checker import check_data_source


def _write(root: Path, rel: str, doc: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def _write_registry(root: Path, entities: list[dict]) -> None:
    _write(root, "contracts/resource-registry.json", {"entities": entities})


# ────────────────────────────────────────────────────────────
# Deductive rules per op
# ────────────────────────────────────────────────────────────

def test_op_get_with_extra_filter_flagged_with_specific_message(tmp_path):
    """The Drive-detail bug: ``op:get`` should never carry a ``filter``."""
    _write(tmp_path, "src/schemas/drives/[id].json", {
        "route": "/drives/[id]",
        "dataSources": [{
            "name": "drive", "entity": "Drive", "op": "get",
            "filter": {"field": "id", "op": "eq", "value": "{{params.id}}"},
        }],
    })
    result = check_data_source(tmp_path, "src/schemas/drives/[id].json")
    assert result["error"] is None if "error" in result else True
    vs = result["violations"]
    assert len(vs) == 1
    v = vs[0]
    assert v["kind"] == "extra_key"
    assert v["key"] == "filter"
    assert v["op"] == "get"
    # Targeted message names the URL-params mechanism.
    assert "url params" in v["message"].lower()


def test_op_get_clean_shape_no_violations(tmp_path):
    _write(tmp_path, "src/schemas/things/[id].json", {
        "route": "/things/[id]",
        "dataSources": [{"name": "thing", "entity": "Thing", "op": "get"}],
    })
    result = check_data_source(tmp_path, "src/schemas/things/[id].json")
    assert result["violations"] == []


def test_op_list_accepts_filter_sort_limit(tmp_path):
    _write(tmp_path, "src/schemas/things/index.json", {
        "route": "/things",
        "dataSources": [{
            "name": "things", "entity": "Thing", "op": "list",
            "filter": {"field": "status", "op": "eq", "value": "active"},
            "sort":   [{"field": "createdAt", "dir": "desc"}],
            "limit":  20,
        }],
    })
    result = check_data_source(tmp_path, "src/schemas/things/index.json")
    assert result["violations"] == []


def test_op_list_with_where_flagged_as_wrong_key(tmp_path):
    """``op:list`` should use ``filter``, not ``where``."""
    _write(tmp_path, "src/schemas/xs/index.json", {
        "route": "/xs",
        "dataSources": [{
            "name": "xs", "entity": "X", "op": "list",
            "where": {"field": "id", "op": "eq", "value": "1"},
        }],
    })
    result = check_data_source(tmp_path, "src/schemas/xs/index.json")
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["kind"] == "extra_key"
    assert v["key"] == "where"
    assert "filter" in v["message"].lower()


def test_op_aggregate_missing_metrics_flagged(tmp_path):
    _write(tmp_path, "src/schemas/stats/index.json", {
        "route": "/stats",
        "dataSources": [{"name": "stat", "entity": "Thing", "op": "aggregate"}],
    })
    result = check_data_source(tmp_path, "src/schemas/stats/index.json")
    assert any(v["kind"] == "missing_key" and v["key"] == "metrics"
               for v in result["violations"])


def test_op_series_missing_groupby_and_metric_flagged(tmp_path):
    _write(tmp_path, "src/schemas/chart/index.json", {
        "route": "/chart",
        "dataSources": [{"name": "chart", "entity": "Thing", "op": "series"}],
    })
    result = check_data_source(tmp_path, "src/schemas/chart/index.json")
    keys = {v["key"] for v in result["violations"] if v["kind"] == "missing_key"}
    assert keys == {"groupBy", "metric"}


def test_op_series_with_groupby_metric_no_violation(tmp_path):
    _write(tmp_path, "src/schemas/chart/index.json", {
        "route": "/chart",
        "dataSources": [{
            "name": "chart", "entity": "Thing", "op": "series",
            "groupBy": "status", "metric": "count",
        }],
    })
    result = check_data_source(tmp_path, "src/schemas/chart/index.json")
    assert result["violations"] == []


def test_unknown_op_generic_extra_key_still_reasonable(tmp_path):
    """An op we don't know about — we skip the allowed-key check but
    still parse the shape without crashing."""
    _write(tmp_path, "src/schemas/mystery/index.json", {
        "route": "/mystery",
        "dataSources": [{"name": "m", "entity": "Thing", "op": "brew",
                         "coffee": "espresso"}],
    })
    result = check_data_source(tmp_path, "src/schemas/mystery/index.json")
    # No allowed-set for "brew" → nothing flagged. The tool doesn't
    # invent violations for ops it doesn't know.
    assert result["violations"] == []


# ────────────────────────────────────────────────────────────
# Missing op
# ────────────────────────────────────────────────────────────

def test_dataSource_missing_op_flagged(tmp_path):
    _write(tmp_path, "src/schemas/x.json", {
        "route": "/x",
        "dataSources": [{"name": "x", "entity": "Thing"}],
    })
    result = check_data_source(tmp_path, "src/schemas/x.json")
    assert any(v["kind"] == "missing_op" for v in result["violations"])


# ────────────────────────────────────────────────────────────
# Registry entity check
# ────────────────────────────────────────────────────────────

def test_unknown_entity_flagged_against_registry(tmp_path):
    _write_registry(tmp_path, [{"name": "Drive", "slug": "drives"}])
    _write(tmp_path, "src/schemas/xs.json", {
        "route": "/xs",
        "dataSources": [{"name": "xs", "entity": "Zebra", "op": "list"}],
    })
    result = check_data_source(tmp_path, "src/schemas/xs.json")
    assert any(
        v["kind"] == "unknown_entity" and v["key"] == "entity"
        and "Zebra" in v["message"]
        for v in result["violations"]
    )


def test_known_entity_by_name_not_flagged(tmp_path):
    _write_registry(tmp_path, [{"name": "Drive", "slug": "drives"}])
    _write(tmp_path, "src/schemas/xs.json", {
        "route": "/xs",
        "dataSources": [{"name": "d", "entity": "Drive", "op": "list"}],
    })
    result = check_data_source(tmp_path, "src/schemas/xs.json")
    assert not any(v["kind"] == "unknown_entity" for v in result["violations"])


def test_known_entity_by_slug_not_flagged(tmp_path):
    _write_registry(tmp_path, [{"name": "Drive", "slug": "drives"}])
    _write(tmp_path, "src/schemas/xs.json", {
        "route": "/xs",
        "dataSources": [{"name": "d", "entity": "drives", "op": "list"}],
    })
    result = check_data_source(tmp_path, "src/schemas/xs.json")
    assert not any(v["kind"] == "unknown_entity" for v in result["violations"])


def test_no_registry_skips_entity_check(tmp_path):
    """When there is no registry file, we can't check entity — silent."""
    _write(tmp_path, "src/schemas/xs.json", {
        "route": "/xs",
        "dataSources": [{"name": "d", "entity": "Anything", "op": "list"}],
    })
    result = check_data_source(tmp_path, "src/schemas/xs.json")
    assert not any(v["kind"] == "unknown_entity" for v in result["violations"])


# ────────────────────────────────────────────────────────────
# Error paths
# ────────────────────────────────────────────────────────────

def test_missing_file_returns_error(tmp_path):
    result = check_data_source(tmp_path, "src/schemas/nope.json")
    assert "not found" in (result.get("error") or "").lower()
    assert result["violations"] == []


def test_unparseable_file_returns_error(tmp_path):
    p = tmp_path / "src/schemas/bad.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    result = check_data_source(tmp_path, "src/schemas/bad.json")
    assert result.get("error") is not None


def test_page_without_datasources_returns_error(tmp_path):
    _write(tmp_path, "src/schemas/nothing.json", {"route": "/nothing"})
    result = check_data_source(tmp_path, "src/schemas/nothing.json")
    assert result.get("error") == "page has no dataSources array"


# ────────────────────────────────────────────────────────────
# Payload shape
# ────────────────────────────────────────────────────────────

def test_payload_includes_dataSources_summary(tmp_path):
    """The response echoes each dataSource's (name, entity, op, keys)
    so Smith doesn't have to re-read the schema alongside the tool
    output."""
    _write(tmp_path, "src/schemas/xs.json", {
        "route": "/xs",
        "dataSources": [
            {"name": "xs", "entity": "X", "op": "list", "filter": {}},
            {"name": "ys", "entity": "Y", "op": "get"},
        ],
    })
    result = check_data_source(tmp_path, "src/schemas/xs.json")
    assert result["route"] == "/xs"
    assert result["path"] == "src/schemas/xs.json"
    assert len(result["dataSources"]) == 2
    assert result["dataSources"][0]["name"] == "xs"
    assert result["dataSources"][0]["op"] == "list"
    assert "filter" in result["dataSources"][0]["keys"]
    assert result["dataSources"][1]["op"] == "get"
