"""B13 — the two aggregate-metric dialects, reconciled.

`output/gh0mlpbp/app/src/schemas/items.json` declared

    "totalValue": {"expression": "sum(quantity * price)", "format": "currency"}

while every resolver that reads a metric — the generated app's
`data-engine.computeSimple`, the editor's `preview-resolve.resolveAggregate`,
and the shape `widget_data_source_guard` documents — reads `{"fn", "field"}`.
No parser for the `expression` form existed on either render side, so a
correctly-NAMED aggregate source still resolved to 0. These tests pin the
translation, including the case that has no `field` to translate to.
"""

import json

from services.metric_dialect import (
    normalize_metric,
    normalize_sources,
    parse_expression,
    repair_output_dir,
)


# ── parse_expression ────────────────────────────────────────────────────────

def test_count_of_a_column_is_a_row_count():
    """`count(id)` needs no field: count() takes no column, and carrying `id`
    through made the metric look like it wanted a column that may not exist."""
    assert parse_expression("count(id)") == {"fn": "count"}
    assert parse_expression("count(*)") == {"fn": "count"}
    assert parse_expression("COUNT( DISTINCT owner )") == {"fn": "count"}


def test_a_single_column_becomes_a_field():
    assert parse_expression("sum(price)") == {"fn": "sum", "field": "price"}
    assert parse_expression("avg(rating)") == {"fn": "avg", "field": "rating"}
    assert parse_expression("min(qty)") == {"fn": "min", "field": "qty"}
    assert parse_expression("max(qty)") == {"fn": "max", "field": "qty"}


def test_aliases_fold_onto_the_runtime_functions():
    assert parse_expression("average(rating)") == {"fn": "avg", "field": "rating"}
    assert parse_expression("total(price)") == {"fn": "sum", "field": "price"}


def test_arithmetic_keeps_the_expression_and_emits_no_field():
    """`field` MUST be a column — `cols["quantity * price"]` is undefined and
    `sum(undefined)` throws into the resolver's catch-all 0. A synthetic field
    name would make BOTH sides silently wrong instead of one honestly empty."""
    assert parse_expression("sum(quantity * price)") == {
        "fn": "sum", "expr": "quantity * price"}


def test_anything_that_is_not_an_aggregate_call_is_declined():
    for bad in ("", "   ", "quantity * price", "sum", "median(x)",
                "select count(*) from items", None, 42):
        assert parse_expression(bad) is None


# ── normalize_metric ────────────────────────────────────────────────────────

def test_format_survives_the_translation():
    """A currency tile still has to render as currency."""
    out = normalize_metric({"expression": "sum(quantity * price)",
                            "format": "currency"})
    assert out == {"format": "currency", "fn": "sum", "expr": "quantity * price"}
    assert "expression" not in out


def test_a_machine_readable_fn_wins():
    """An agent that wrote both is taken at its machine-readable word."""
    assert normalize_metric({"fn": "sum", "field": "price",
                             "expression": "count(id)"}) is None


def test_an_unparseable_expression_is_left_exactly_as_it_was():
    assert normalize_metric({"expression": "percentile(0.9, latency)"}) is None


# ── the real artifact ───────────────────────────────────────────────────────

_ITEMS_SOURCES = [
    {"name": "items", "entity": "Item", "op": "list", "limit": 500},
    {"name": "totalInventoryValue", "entity": "Item", "op": "aggregate",
     "metrics": {
         "itemCount": {"expression": "count(id)", "format": "number"},
         "totalValue": {"expression": "sum(quantity * price)",
                        "format": "currency"},
     }},
    {"name": "lowStockCount", "entity": "Item", "op": "aggregate",
     "filter": {"quantity": {"lt": 5}},
     "metrics": {"lowStockCount": {"expression": "count(id)",
                                   "format": "number"}}},
]


def test_the_shipped_items_page_sources_normalise():
    sources = json.loads(json.dumps(_ITEMS_SOURCES))
    assert normalize_sources(sources) == 3
    metrics = sources[1]["metrics"]
    assert metrics["itemCount"]["fn"] == "count"
    assert metrics["totalValue"] == {"format": "currency", "fn": "sum",
                                     "expr": "quantity * price"}
    assert sources[2]["metrics"]["lowStockCount"]["fn"] == "count"
    # A list source has no metrics and must come through untouched.
    assert sources[0] == _ITEMS_SOURCES[0]


def test_normalising_is_idempotent():
    sources = json.loads(json.dumps(_ITEMS_SOURCES))
    normalize_sources(sources)
    assert normalize_sources(sources) == 0


def test_repair_rewrites_a_project_already_on_disk(tmp_path):
    """Generation is fixed at the source, but every project already generated
    carries the old dialect in the page schemas the app and editor read."""
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    page = {"schemaVersion": "2", "id": "PAGE-001", "route": "/items",
            "dataSources": json.loads(json.dumps(_ITEMS_SOURCES)),
            "root": {"type": "Container", "props": {}}}
    (sdir / "items.json").write_text(json.dumps(page, indent=2),
                                     encoding="utf-8")

    report = repair_output_dir(str(tmp_path))
    assert report == {"files": 1, "metrics": 3}

    after = json.loads((sdir / "items.json").read_text(encoding="utf-8"))
    blob = json.dumps(after)
    assert "expression" not in blob
    assert after["dataSources"][1]["metrics"]["totalValue"]["fn"] == "sum"
    # Second run has nothing left to do.
    assert repair_output_dir(str(tmp_path)) == {"files": 0, "metrics": 0}


def test_repair_survives_a_directory_that_is_not_there():
    assert repair_output_dir("no/such/place") == {"files": 0, "metrics": 0}
