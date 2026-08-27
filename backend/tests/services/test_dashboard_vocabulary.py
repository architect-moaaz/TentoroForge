"""Dashboard vocabulary — the domain decides what the landing page shows.

Every archetype vocabulary shapes interior list screens (table vs card-grid,
section splits, empty copy) but nothing reached the dashboard, so every app
opened on the same generic KPI skeleton whatever the industry. These cover
the resolver that turns a vocabulary's ``dashboard_recipe`` into KPI and
section specs bound to the app's REAL entities.
"""
from __future__ import annotations

from services.archetype_vocabulary import ArchetypeVocabulary
from services.dashboard_vocabulary import resolve_dashboard_recipe


def _vocab(**kw) -> ArchetypeVocabulary:
    return ArchetypeVocabulary(id="test-platform", **kw)


RECIPE = {
    "kpis": [
        {"label": "Items in stock", "entity": "products", "op": "count",
         "filter": {"status": "in_stock"}},
        {"label": "Low stock", "entity": "products", "op": "count",
         "filter": {"status": "low_stock"}},
        {"label": "Open POs", "entity": "purchase_orders", "op": "count"},
        {"label": "Suppliers", "entity": "suppliers", "op": "count"},
    ],
    "sections": [
        {"title": "Needs reordering", "entity": "products",
         "filter": {"status": "low_stock"}, "limit": 8},
        {"title": "Recent stock movements", "entity": "stock_movements",
         "shape": "ledger-list", "limit": 10},
    ],
}


def test_recipe_resolves_against_real_entities():
    out = resolve_dashboard_recipe(_vocab(dashboard_recipe=RECIPE),
                                   available={"products", "suppliers"})
    assert [k["label"] for k in out["kpis"]] == [
        "Items in stock", "Low stock", "Suppliers"]        # POs dropped
    assert [s["title"] for s in out["sections"]] == ["Needs reordering"]
    assert out["kpis"][1]["filter"] == {"status": "low_stock"}


def test_entity_slug_matching_is_forgiving():
    """Vocabularies name entities in their own words; apps name them in
    theirs. purchase_orders ↔ purchaseOrders ↔ purchase-orders are one."""
    out = resolve_dashboard_recipe(
        _vocab(dashboard_recipe={"kpis": [
            {"label": "Open POs", "entity": "purchase_orders", "op": "count"}]}),
        available={"purchaseOrders"},
    )
    assert len(out["kpis"]) == 1
    assert out["kpis"][0]["entity"] == "purchaseOrders"   # the APP's name wins


def test_no_recipe_yields_nothing_rather_than_junk():
    out = resolve_dashboard_recipe(_vocab(), available={"products"})
    assert out == {"kpis": [], "sections": []}


def test_nothing_matches_yields_nothing():
    out = resolve_dashboard_recipe(_vocab(dashboard_recipe=RECIPE),
                                   available={"invoices"})
    assert out == {"kpis": [], "sections": []}


def test_empty_state_copy_comes_from_the_vocabulary():
    v = _vocab(dashboard_recipe=RECIPE,
               signature_states={"empty_dashboard": "No activity yet. "
                                 "Metrics populate as stock starts moving."})
    out = resolve_dashboard_recipe(v, available={"products"})
    assert out["empty_copy"].startswith("No activity yet.")


def test_status_badges_ride_along_for_section_tables():
    v = _vocab(dashboard_recipe=RECIPE,
               status_badges={"low_stock": {"variant": "warning",
                                            "label": "Low stock"}})
    out = resolve_dashboard_recipe(v, available={"products"})
    assert out["status_badges"]["low_stock"]["variant"] == "warning"


def test_kpi_cap_keeps_the_row_scannable():
    many = {"kpis": [{"label": f"M{i}", "entity": "products", "op": "count"}
                     for i in range(9)]}
    out = resolve_dashboard_recipe(_vocab(dashboard_recipe=many),
                                   available={"products"}, max_kpis=4)
    assert len(out["kpis"]) == 4


# ── binding recipe filters to one app's real enum ──────────────────────
#
# Vocabulary filters name candidate spellings because the industry's word
# and a given app's word often differ. These cover what happens when they
# do — and when nothing matches at all.

from dataclasses import dataclass, field as _dc_field


@dataclass
class _V:
    id: str = "inventory-platform"
    dashboard_recipe: dict = _dc_field(default_factory=dict)
    signature_states: dict = _dc_field(default_factory=dict)
    status_badges: dict = _dc_field(default_factory=dict)


def _entity(cols: dict, enums: dict | None = None):
    return {"fields": [
        {"name": n, "type": t,
         **({"enum_values": (enums or {})[n]} if n in (enums or {}) else {})}
        for n, t in cols.items()
    ]}


def test_candidate_filter_resolves_to_the_spelling_this_app_uses():
    v = _V(dashboard_recipe={"kpis": [
        {"label": "Low stock", "entity": "products", "op": "count",
         "filter": {"status": ["low_stock", "reorder"]}}]})
    out = resolve_dashboard_recipe(
        v, ["products"],
        entities={"products": _entity({"status": "text"},
                                      {"status": ["in_stock", "reorder"]})})
    assert out["kpis"][0]["filter"] == {"status": "reorder"}


def test_kpi_is_dropped_when_no_candidate_can_ever_match():
    """A tile pinned to an impossible status always reads zero, which
    looks like a broken metric rather than an honest one."""
    v = _V(dashboard_recipe={"kpis": [
        {"label": "Low stock", "entity": "products", "op": "count",
         "filter": {"status": ["low_stock"]}}]})
    out = resolve_dashboard_recipe(
        v, ["products"],
        entities={"products": _entity({"status": "text"},
                                      {"status": ["active", "archived"]})})
    assert out["kpis"] == []


def test_section_survives_a_filter_it_cannot_bind():
    """Losing a filter costs a section its focus, not its existence — an
    unfiltered working list is still worth showing."""
    v = _V(dashboard_recipe={"sections": [
        {"title": "Needs reordering", "entity": "products",
         "filter": {"status": ["low_stock"]}, "limit": 8}]})
    out = resolve_dashboard_recipe(
        v, ["products"],
        entities={"products": _entity({"status": "text"},
                                      {"status": ["active"]})})
    assert len(out["sections"]) == 1
    assert "filter" not in out["sections"][0]
    assert out["sections"][0]["limit"] == 8


def test_sum_over_a_column_the_app_lacks_degrades_to_a_count():
    """Better an honest count than a tile that renders blank."""
    v = _V(dashboard_recipe={"kpis": [
        {"label": "Inventory value", "entity": "products",
         "op": "sum", "field": "price"}]})
    out = resolve_dashboard_recipe(
        v, ["products"], entities={"products": _entity({"name": "text"})})
    assert out["kpis"][0]["op"] == "count"
    assert "field" not in out["kpis"][0]


def test_without_entity_metadata_the_vocabulary_is_trusted():
    """Callers that have only entity names still get a usable recipe —
    candidate lists collapse to their preferred value."""
    v = _V(dashboard_recipe={"kpis": [
        {"label": "Low stock", "entity": "products", "op": "count",
         "filter": {"status": ["low_stock", "reorder"]}}]})
    out = resolve_dashboard_recipe(v, ["products"])
    assert out["kpis"][0]["filter"] == {"status": "low_stock"}
