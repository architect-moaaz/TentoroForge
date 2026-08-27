"""The domain owns which row a list puts on top.

The defect these pin: with reference screens attached the composer sorted
stock by ``updatedAt desc`` in 3/3 runs and ``qtyAvailable asc`` in 0/3.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from services.list_sort_authority import apply_list_sort
from services.page_vocabulary import resolve_page_recipe


@dataclass
class _Vocab:
    id: str = "inventory-platform"
    page_recipes: dict = field(default_factory=dict)


_STOCK_COLS = ["id", "skuId", "qtyOnHand", "qtyAvailable", "updatedAt"]

_PLAN = {
    "data_models": [
        {"name": "StockLevel",
         "fields": [{"name": c, "type": "text"} for c in _STOCK_COLS]},
        {"name": "Movement",
         "fields": [{"name": c, "type": "text"} for c in ("id", "occurredAt")]},
    ]
}


def _vocab(**recipes):
    return _Vocab(page_recipes=recipes or {
        "stock_levels": {"list_order": {"field": "qtyAvailable", "dir": "asc"}},
    })


def _schema(*sources):
    return {"dataSources": list(sources), "root": {"type": "Stack"}}


def _list_src(name="stock", entity="StockLevel", **extra):
    return {"name": name, "entity": entity, "op": "list", **extra}


# ── the defect ─────────────────────────────────────────────────────

def test_recency_default_is_replaced_by_the_domains_choice():
    s = _schema(_list_src(orderBy=[{"field": "updatedAt", "dir": "desc"}]))
    changed = apply_list_sort(s, _PLAN, _vocab())
    assert s["dataSources"][0]["orderBy"] == [
        {"field": "qtyAvailable", "dir": "asc"}]
    assert changed[0]["was"] == [{"field": "updatedAt", "dir": "desc"}]


def test_a_missing_order_is_filled_in():
    """The other failure mode seen live: the composer omitted orderBy
    entirely, leaving rows in arbitrary database order."""
    s = _schema(_list_src())
    apply_list_sort(s, _PLAN, _vocab())
    assert s["dataSources"][0]["orderBy"] == [
        {"field": "qtyAvailable", "dir": "asc"}]


# ── silence means the composer keeps its choice ────────────────────

def test_entity_with_no_recipe_is_left_alone():
    s = _schema(_list_src(name="moves", entity="Movement",
                          orderBy=[{"field": "occurredAt", "dir": "desc"}]))
    assert apply_list_sort(s, _PLAN, _vocab()) == []
    assert s["dataSources"][0]["orderBy"] == [
        {"field": "occurredAt", "dir": "desc"}]


def test_no_vocabulary_changes_nothing():
    s = _schema(_list_src(orderBy=[{"field": "updatedAt", "dir": "desc"}]))
    assert apply_list_sort(s, _PLAN, None) == []
    assert s["dataSources"][0]["orderBy"] == [
        {"field": "updatedAt", "dir": "desc"}]


# ── conservatism ───────────────────────────────────────────────────

def test_column_the_app_never_built_is_dropped_not_emitted():
    """Ordering by a missing column is a runtime error, not a near-miss."""
    v = _vocab(stock_levels={"list_order": {"field": "reorderPoint",
                                            "dir": "asc"}})
    s = _schema(_list_src(orderBy=[{"field": "updatedAt", "dir": "desc"}]))
    assert apply_list_sort(s, _PLAN, v) == []
    assert s["dataSources"][0]["orderBy"] == [
        {"field": "updatedAt", "dir": "desc"}]


def test_only_row_returning_reads_are_touched():
    for op in ("get", "aggregate", "series"):
        s = _schema(_list_src(op=op))
        assert apply_list_sort(s, _PLAN, _vocab()) == [], op
        assert "orderBy" not in s["dataSources"][0]


def test_recency_stays_where_the_domain_asks_for_it():
    """The rule is "the domain chooses", not "never sort by date"."""
    v = _vocab(movement={"list_order": {"field": "occurredAt", "dir": "desc"}})
    s = _schema(_list_src(name="moves", entity="Movement"))
    apply_list_sort(s, _PLAN, v)
    assert s["dataSources"][0]["orderBy"] == [
        {"field": "occurredAt", "dir": "desc"}]


def test_running_twice_changes_nothing_the_second_time():
    s = _schema(_list_src(orderBy=[{"field": "updatedAt", "dir": "desc"}]))
    assert apply_list_sort(s, _PLAN, _vocab())
    assert apply_list_sort(s, _PLAN, _vocab()) == []


def test_garbage_shapes_do_not_raise():
    for bad in (None, {}, {"dataSources": "nope"}, {"dataSources": [None, 7]}):
        assert apply_list_sort(bad, _PLAN, _vocab()) == []


# ── the resolver half ──────────────────────────────────────────────

def test_resolver_normalises_direction():
    v = _vocab(stock_levels={"list_order": {"field": "qtyAvailable",
                                            "dir": "DESC"}})
    r = resolve_page_recipe(v, "StockLevel", _PLAN["data_models"][0])
    assert r["list_order"] == {"field": "qtyAvailable", "dir": "desc"}


def test_resolver_defaults_a_bogus_direction_to_asc():
    v = _vocab(stock_levels={"list_order": {"field": "qtyAvailable",
                                            "dir": "sideways"}})
    r = resolve_page_recipe(v, "StockLevel", _PLAN["data_models"][0])
    assert r["list_order"]["dir"] == "asc"


def test_an_order_survives_even_when_every_column_missed():
    """The columns and the order are independent judgements — losing the
    column set is no reason to discard a usable ordering."""
    v = _vocab(stock_levels={"list_columns": ["nope", "alsoNope"],
                             "list_order": {"field": "qtyAvailable",
                                            "dir": "asc"}})
    r = resolve_page_recipe(v, "StockLevel", _PLAN["data_models"][0])
    assert r["list_columns"] == []
    assert r["list_order"] == {"field": "qtyAvailable", "dir": "asc"}
