"""The page recipe binds a domain's reading order to one app's columns."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.apply_collection_maquette import _maquette_columns
from services.page_vocabulary import resolve_page_recipe


@dataclass
class _Vocab:
    id: str = "inventory-platform"
    page_recipes: dict = field(default_factory=dict)


_RECIPE = {
    "products": {
        "list_columns": ["sku", "name", "status", "quantityOnHand", "reorderPoint"],
        "filter_chips": ["status", "category"],
        "detail_sections": [
            {"label": "Item", "fields": ["sku", "name"]},
            {"label": "Stock", "fields": ["quantityOnHand", "binLocation"]},
        ],
    }
}


def _vocab():
    return _Vocab(page_recipes=_RECIPE)


def _entity(*cols):
    return {"fields": [{"name": c, "type": "text"} for c in cols]}


def test_columns_the_app_lacks_are_dropped_not_invented():
    r = resolve_page_recipe(_vocab(), "products",
                            _entity("sku", "name", "status"))
    assert r["list_columns"] == ["sku", "name", "status"]


def test_app_spelling_wins_over_vocabulary_spelling():
    """The binding has to use the name the app really built, or it
    resolves to nothing at runtime."""
    r = resolve_page_recipe(_vocab(), "products",
                            _entity("sku", "name", "quantity_on_hand"))
    assert r["list_columns"] == ["sku", "name", "quantity_on_hand"]


def test_entity_name_matching_tolerates_planner_spelling():
    r = resolve_page_recipe(_vocab(), "Product",
                            _entity("sku", "name", "status"))
    assert r["list_columns"] == ["sku", "name", "status"]


def test_section_with_no_surviving_fields_disappears():
    """A heading over an empty card is worse than no heading."""
    r = resolve_page_recipe(_vocab(), "products", _entity("sku", "name"))
    assert [s["label"] for s in r["detail_sections"]] == ["Item"]


def test_entity_without_a_recipe_yields_nothing():
    assert resolve_page_recipe(_vocab(), "warehouses", _entity("name")) == {}


def test_no_vocabulary_yields_nothing():
    assert resolve_page_recipe(None, "products", _entity("sku")) == {}


# ── the composer seam ────────────────────────────────────────────────

_REAL = {"id": "uuid", "createdAt": "timestamp", "sku": "text",
         "name": "text", "status": "text", "quantityOnHand": "int"}


def test_maquette_columns_prefers_the_authors_own_choice():
    mq = {"columns": [{"name": "name"}, {"name": "status"}]}
    assert _maquette_columns(mq, _REAL, vocabulary=_vocab(),
                             entity="products") == ["name", "status"]


def test_maquette_columns_fall_back_to_the_domain_not_the_database():
    """Registry order is insertion order — it led tables with id and
    createdAt while the identifying column sat off-screen."""
    got = _maquette_columns({}, _REAL, vocabulary=_vocab(), entity="products")
    assert got == ["sku", "name", "status", "quantityOnHand"]
    assert "id" not in got and "createdAt" not in got


def test_maquette_columns_still_work_with_no_vocabulary():
    got = _maquette_columns({}, _REAL)
    assert "id" not in got
    assert got[0] == "createdAt"   # registry order, minus the key columns


# ── quality floor ────────────────────────────────────────────────────
#
# A recipe is written in the industry's column names; a given app may
# have picked others. These cover what happens when the overlap is poor
# — the answer is never "ship whatever matched".

_CRM = _Vocab(id="crm-platform", page_recipes={"deals": {
    "list_columns": ["name", "company", "stage", "amount", "closeDate", "owner"],
    "detail_sections": [{"label": "Deal", "fields": ["name", "stage"]}],
}})


def test_a_recipe_that_loses_its_identifying_column_leads_with_the_apps_own():
    """`amount, closeDate` is not a list of deals — nobody can tell the
    rows apart."""
    got = resolve_page_recipe(
        _CRM, "deals", _entity("title", "amount", "closeDate", "status"))
    assert got["list_columns"][0] == "title"


def test_barely_matching_recipe_defers_to_the_generic_column_set():
    got = resolve_page_recipe(_CRM, "deals", _entity("amount", "notes"))
    assert not got.get("list_columns")


def test_a_good_match_keeps_the_domains_own_order():
    got = resolve_page_recipe(
        _CRM, "deals", _entity("name", "company", "stage", "amount"))
    assert got["list_columns"] == ["name", "company", "stage", "amount"]
