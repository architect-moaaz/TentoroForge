"""B12 — a Stat whose binding ROOT names no declared dataSource.

`output/gh0mlpbp/app/src/schemas/items.json` shipped three KPI tiles bound to
`{{metrics.list_total_inventory_value}}`, `{{metrics.list_low_stock_items}}`
and `{{metrics.list_items}}` on a page whose dataSources were named `items`,
`totalInventoryValue` and `lowStockCount`. There was no `metrics` source. The
renderer was later fixed to never leak a raw `{{…}}` template, which was right
and turned three wrong tiles into three BLANK ones.

Two generators disagreed:

  * `page_widgets` binds every KPI tile into a `metrics` namespace.
  * `data_sources` is the only thing that ever declared it — and `plan_page`
    read `carried or data_sources(...)`, so a composer-authored layout (which
    carries its own dataSources, and is now the default) short-circuited it.

`data_sources` even raises `PlanError` for a binding that names no fetchable
data, with a comment about the literal `{{overdue.value}}` that once shipped —
but on the carried path it never ran, so the check that existed for exactly
this could not fire.

These tests are built from the real Blueprint's shape.
"""

import json

import pytest

from services.blueprint.page_planner import (
    PlanError,
    bind_widget_metrics,
    data_sources,
    plan_page,
    widget_metrics,
)


# ── the Blueprint, as the Inventory app actually declared it ────────────────

def _doc() -> dict:
    return {
        "data": {"entities": [{
            "id": "ENTITY-001", "name": "Item", "table": "items",
            "fields": [
                {"name": "name", "type": "text"},
                {"name": "quantity", "type": "integer"},
                {"name": "category", "type": "text"},
                {"name": "price", "type": "decimal"},
            ],
        }]},
        "pages": [{
            "id": "PAGE-001", "route": "/items", "name": "Inventory Items",
            "module": "MODULE-001", "pattern": "entity_list",
            "data": {"primaryEntity": "ENTITY-001"},
        }],
        "widgets": [
            {"id": "WIDGET-001", "page": "PAGE-001", "kind": "metric",
             "label": "Total Inventory Value",
             "dataSource": {"entity": "ENTITY-001", "op": "list",
                            "fields": ["quantity", "price"]}},
            {"id": "WIDGET-002", "page": "PAGE-001", "kind": "metric",
             "label": "Low Stock Items",
             "dataSource": {"entity": "ENTITY-001", "op": "list",
                            "fields": ["name", "quantity"],
                            "filter": {"quantity": "<5"}}},
            {"id": "WIDGET-003", "page": "PAGE-001", "kind": "table",
             "label": "Items",
             "dataSource": {"entity": "ENTITY-001", "op": "list",
                            "fields": ["name", "category"]}},
        ],
    }


#: The composer's own dataSources — the ones `carried` used to win with.
def _composed_sources() -> list[dict]:
    return [
        {"name": "items", "entity": "ENTITY-001", "op": "list", "limit": 500,
         "orderBy": {"createdAt": "desc"}},
        {"name": "totalInventoryValue", "entity": "ENTITY-001",
         "op": "aggregate", "metrics": {
             "itemCount": {"expression": "count(id)", "format": "number"},
             "totalValue": {"expression": "sum(quantity * price)",
                            "format": "currency"}}},
        {"name": "lowStockCount", "entity": "ENTITY-001", "op": "aggregate",
         "filter": {"quantity": {"lt": 5}},
         "metrics": {"lowStockCount": {"expression": "count(id)",
                                       "format": "number"}}},
    ]


def _layout() -> dict:
    """The composed tree: a Grid of Stat tiles repeated over the page widgets,
    which is where `{{metrics.<key>}}` is minted."""
    return {
        "page": "PAGE-001", "pattern": "entity_list", "composedBy": "agent",
        "dataSources": _composed_sources(),
        "root": {"type": "Container", "props": {"maxWidth": "xl"}, "children": [
            {"type": "Grid", "props": {"columns": 2, "gap": "16px"},
             "children": [{"type": "Stat", "repeat": "widgets",
                           "props": {"label": "$item.label",
                                     "trend": "neutral",
                                     "value": "$item.value"}}]},
            {"type": "Table", "props": {"rows": "{{items}}", "columns": [
                {"key": "name", "label": "Name"}]}},
        ]},
    }


_CATALOG = {
    "Container": {"props": {"maxWidth": {"type": "string"}}},
    "Grid": {"props": {"columns": {"type": "number"}, "gap": {"type": "string"}}},
    "Stat": {"props": {"label": {"type": "string"}, "value": {"type": "string"},
                       "trend": {"type": "string"}}},
    "Table": {"props": {"rows": {"type": "string"}, "columns": {"type": "array"}}},
}


def _bindings(node) -> list[str]:
    import re
    return re.findall(r"\{\{[^}]*\}\}", json.dumps(node))


# ── the regression: the whole page, planned ─────────────────────────────────

def test_no_stat_is_left_bound_to_a_source_the_page_never_declares():
    """The bug, end to end: every binding root must name a declared source."""
    schema = plan_page(_doc(), _doc()["pages"][0], _layout(), _CATALOG)
    names = {s["name"] for s in schema["dataSources"]}
    for binding in _bindings(schema["root"]):
        root = binding.strip("{} ").split(".")[0]
        assert root in names, f"{binding} names no dataSource ({sorted(names)})"


def test_each_tile_lands_on_the_metric_the_composer_designed_for_it():
    """Declaring a fresh `metrics` source would resolve the binding to a row
    count the composer never asked for — a tile reading "Total Inventory Value"
    over a count is worse than a blank one. The composer DID declare a
    sum(quantity*price); the tile is rebound onto it."""
    schema = plan_page(_doc(), _doc()["pages"][0], _layout(), _CATALOG)
    stats = {n["props"]["label"]: n["props"]["value"]
             for n in _iter(schema["root"]) if n.get("type") == "Stat"}
    assert stats["Total Inventory Value"] == "{{totalInventoryValue.totalValue}}"
    assert stats["Low Stock Items"] == "{{lowStockCount.lowStockCount}}"
    assert stats["Items"] == "{{totalInventoryValue.itemCount}}"


def test_the_carried_metrics_are_normalised_to_the_runtime_dialect():
    """B13 at the point of generation — no `expression` reaches a resolver."""
    schema = plan_page(_doc(), _doc()["pages"][0], _layout(), _CATALOG)
    blob = json.dumps(schema["dataSources"])
    assert "expression" not in blob
    agg = next(s for s in schema["dataSources"]
               if s["name"] == "totalInventoryValue")
    assert agg["metrics"]["totalValue"] == {
        "format": "currency", "fn": "sum", "expr": "quantity * price"}


def _iter(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter(v)


# ── the gap-fill, when nothing declared fits ────────────────────────────────

def test_a_tile_no_declared_metric_fits_gets_a_real_source_declared():
    """With no aggregate source to rebind onto, the `metrics` namespace is
    declared rather than left dangling — WITH its metric map (see below)."""
    layout = _layout()
    layout["dataSources"] = [s for s in _composed_sources()
                             if s["op"] == "list"]
    schema = plan_page(_doc(), _doc()["pages"][0], layout, _CATALOG)
    metrics = next(s for s in schema["dataSources"] if s["name"] == "metrics")
    assert metrics["op"] == "aggregate"
    assert metrics["entity"] == "Item"
    assert set(metrics["metrics"]) == {
        "list_total_inventory_value", "list_low_stock_items", "list_items"}


def test_the_metrics_source_is_never_declared_empty():
    """It used to be emitted as a bare {name, entity, op:"aggregate"}.
    `resolveAggregate` iterates `source.metrics`; an empty map yields `{}`, so
    every `{{metrics.<key>}}` came back undefined and the tile rendered blank —
    a dangling binding wearing a declared source's name."""
    doc, page = _doc(), _doc()["pages"][0]
    root = {"type": "Stat",
            "props": {"value": "{{metrics.list_items}}", "label": "Items"}}
    sources = data_sources(doc, page, doc["data"]["entities"][0], root)
    metrics = next(s for s in sources if s["name"] == "metrics")
    assert metrics["metrics"], "an aggregate source with no metrics resolves to {}"


def test_a_declared_aggregation_beats_a_count():
    """A widget that says how to aggregate is taken at its word; one that does
    not gets a row count, which is the only thing true of any entity."""
    doc = _doc()
    doc["widgets"][0]["dataSource"].update({"aggregation": "sum",
                                            "field": "price"})
    m = widget_metrics(doc, "PAGE-001")
    assert m["list_sum_total_inventory_value"] == {"fn": "sum", "field": "price"}
    assert m["list_items"] == {"fn": "count"}


def test_an_equality_filter_is_carried_onto_the_metric():
    doc = _doc()
    doc["widgets"][1]["dataSource"]["filter"] = {"status": "low"}
    m = widget_metrics(doc, "PAGE-001")
    assert m["list_low_stock_items"] == {"fn": "count",
                                         "filter": {"status": "low"}}


def test_a_comparison_written_as_prose_is_not_carried_as_an_equality():
    """The Blueprint writes `{"quantity": "<5"}`. The runtime compiles `filter`
    to `eq(col, value)`, so carrying it would compare quantity to the literal
    string "<5", match nothing, and report a confident 0."""
    m = widget_metrics(_doc(), "PAGE-001")
    assert m["list_low_stock_items"] == {"fn": "count"}


# ── failing loudly ──────────────────────────────────────────────────────────

def test_a_binding_that_names_nothing_fetchable_fails_the_page():
    """The loud half. `data_sources` has always raised for this; on the carried
    path it never ran, so `/items` shipped instead of failing."""
    layout = _layout()
    layout["root"]["children"].append(
        {"type": "Stat", "props": {"label": "Overdue",
                                   "value": "{{overdue.value}}"}})
    with pytest.raises(PlanError, match="overdue"):
        plan_page(_doc(), _doc()["pages"][0], layout, _CATALOG)


def test_a_repeat_alias_is_a_scope_not_a_dangling_binding():
    """`{{order.ref}}` inside a Repeat over `items` names a row, not a fetch.
    Reporting it would fail pages that render correctly."""
    doc, page = _doc(), _doc()["pages"][0]
    root = {"type": "Repeat", "bind": "items", "props": {"as": "order"},
            "children": [{"type": "Text", "props": {"content": "{{order.ref}}"}}]}
    assert data_sources(doc, page, doc["data"]["entities"][0], root,
                        declared={"items"}) == []


def test_the_actor_scope_is_not_a_dangling_binding():
    doc, page = _doc(), _doc()["pages"][0]
    root = {"type": "Text", "props": {"content": "Hi {{user.name}}"}}
    assert data_sources(doc, page, doc["data"]["entities"][0], root) == []


# ── the matcher's own restraint ─────────────────────────────────────────────

def test_two_equally_good_metrics_are_not_guessed_between():
    """An ambiguous match is left for the gap-fill to declare honestly, rather
    than resolved to whichever candidate happened to sort first."""
    doc = _doc()
    doc["widgets"] = [doc["widgets"][0]]
    sources = [{"name": "a", "entity": "Item", "op": "aggregate",
                "metrics": {"totalValue": {"fn": "sum", "field": "price"}}},
               {"name": "b", "entity": "Item", "op": "aggregate",
                "metrics": {"totalValue": {"fn": "sum", "field": "price"}}}]
    root = {"type": "Stat", "props": {
        "value": "{{metrics.list_total_inventory_value}}"}}
    assert bind_widget_metrics(doc, doc["pages"][0], root, sources) == 0


def test_no_shared_word_is_no_match():
    doc = _doc()
    doc["widgets"] = [doc["widgets"][0]]
    sources = [{"name": "churn", "entity": "Item", "op": "aggregate",
                "metrics": {"weeklyRate": {"fn": "count"}}}]
    root = {"type": "Stat", "props": {
        "value": "{{metrics.list_total_inventory_value}}"}}
    assert bind_widget_metrics(doc, doc["pages"][0], root, sources) == 0
