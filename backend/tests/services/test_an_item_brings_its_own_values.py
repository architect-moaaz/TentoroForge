"""SnapIT (2026-09-29): every listing's `currency` was extracted, then each was
saved with the literal "INR" — a StockX price of $60 showed as ₹60, and the
results page's fmtINR put "₹" on every price and one range across currencies."""
from __future__ import annotations

from services.blueprint.functional_completeness import authoring_findings, item_value_findings


def _doc(currency, loop=True):
    extract = {"key": "extract_listings", "type": "ai_extract",
               "config": {"aiExtractMany": True, "aiExtractFields": ["title", "price", "currency"],
                          "aiInput": "{{crawl.output}}"}}
    if loop:
        save = {"key": "persist", "type": "action", "config": {
            "actionType": "for_each", "items": "{{extract_listings.output}}", "as": "listing",
            "steps": [{"key": "merchant_product", "config": {"actionType": "db_insert", "table": "merchant_products",
                       "values": {"title": "{{listing.title}}", "price": "{{listing.price}}", "currency": currency,
                                  "status": "active"}}}]}}
    else:
        save = {"key": "save", "type": "action", "config": {
            "actionType": "db_insert", "table": "merchant_products",
            "values": {"rows": "{{extract_listings.output}}", "currency": currency}}}
    return {"workflows": [{"id": "FLOW-001", "name": "Identify Product From Snap", "steps": [extract, save]}]}


def test_a_literal_for_a_field_each_item_carries_is_named():
    found = item_value_findings(_doc("INR"))
    assert len(found) == 1 and found[0]["rule"] == "item-value-fixed"
    detail = found[0]["detail"]
    assert 'step \'merchant_product\': writes \'currency\' as "INR" for every item' in detail
    assert '`{{listing.currency ?? "INR"}}`' in detail


def test_reading_it_from_the_item_passes():
    assert item_value_findings(_doc('{{listing.currency ?? "INR"}}')) == []


def test_a_field_the_items_do_not_carry_may_be_fixed():
    # `status` is not an extracted field: a literal starting state is fine.
    assert all("'status'" not in f["detail"] for f in item_value_findings(_doc("INR")))


def test_a_whole_list_insert_is_held_to_the_same():
    assert "the item's own `currency`" in item_value_findings(_doc("INR", loop=False))[0]["detail"]


def test_the_author_hears_it():
    assert any(f["rule"] == "item-value-fixed" for f in authoring_findings(_doc("INR")))


def test_authors_are_told():
    from services.blueprint.executors import NODE_TASKS
    from services.blueprint.ui_engineer import DESIGN_PRINCIPLES
    assert "never written as one literal for all of them" in NODE_TASKS["workflow_steps"]
    assert "MONEY SAYS ITS CURRENCY" in DESIGN_PRINCIPLES and "never a fixed symbol" in DESIGN_PRINCIPLES
