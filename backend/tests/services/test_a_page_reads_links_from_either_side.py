"""A page can show a record that points AT it, and a count that belongs to no one.

HippieKit's measured rebuild (2026-09-21) spent most of its twelve
page_details repairs on two facts the content vocabulary could not say:

* the Profile page — a Shopper — wanted "Current plan". Shopper holds no plan;
  a Subscription holds `shopperId` and `planId`. `related` only follows a key
  the page's own record holds, so every attempt was refused with "`via` must
  be a foreign key of Shopper";
* the staff Subscribers page wanted "Active: 42" — every Subscription whose
  status is active. `count` demanded a `via` pointing at a record, and a staff
  overview has none.

Both were the right request. The validator dropped them, the observer then
(correctly) found the page incomplete, and the repair asked for the same thing
again — a loop no number of rounds can settle. `reverse` and a `count` without
`via` let the author say what the reader needs; the SDK already had the reads.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint.page_content import content_brief, content_findings, requested_fields

SHOPPER, PLAN, SUB = "ENTITY-001", "ENTITY-010", "ENTITY-011"


def _doc():
    return {"data": {"entities": [
        {"id": SHOPPER, "name": "Shopper", "labelField": "displayName", "fields": [
            {"name": "id", "type": "uuid"}, {"name": "displayName", "type": "string"}]},
        {"id": PLAN, "name": "Plan", "labelField": "name", "fields": [
            {"name": "id", "type": "uuid"}, {"name": "name", "type": "string"}]},
        {"id": SUB, "name": "Subscription", "labelField": "status", "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "shopperId", "type": "uuid", "references": SHOPPER},
            {"name": "planId", "type": "uuid", "references": PLAN},
            {"name": "status", "type": "enum", "enumValues": ["active", "canceled"]},
            {"name": "renewalDate", "type": "date"},
            {"name": "createdAt", "type": "timestamp"}]},
    ]}, "pages": []}


def _page(*content, route="/profile/[id]", primary=SHOPPER):
    return {"id": "PAGE-013", "route": route, "name": "Profile",
            "data": {"primaryEntity": primary} if primary else {}, "content": list(content)}


def _item(label, **source):
    return {"label": label, "source": source}


CURRENT_PLAN = _item("Current plan", kind="reverse", entity=SUB, via="shopperId",
                     where={"status": "active"}, then={"via": "planId", "entity": PLAN, "field": "name"})
RENEWAL = _item("Renews on", kind="reverse", entity=SUB, via="shopperId",
                where={"status": "active"}, field="renewalDate")
ACTIVE = _item("Active", kind="count", entity=SUB, where={"status": "active"})
EVERYONE = _item("Total subscribers", kind="count", entity=SUB)


def test_the_plan_a_shopper_is_on_resolves_through_the_subscription():
    assert content_findings(_page(CURRENT_PLAN, RENEWAL), _doc()) == []


def test_a_count_over_the_whole_table_needs_no_record():
    page = _page(ACTIVE, EVERYONE, route="/staff/subscribers", primary=None)
    assert content_findings(page, _doc()) == []


@pytest.mark.parametrize("item, fault", [
    (_item("Plan", kind="reverse", entity=SUB, via="planId"), "references ENTITY-010, not Shopper"),
    (_item("Plan", kind="reverse", entity=SUB, via="nope"), "`via` must be the field of Subscription"),
    (_item("Plan", kind="reverse", entity=SUB, via="shopperId", where={"tier": "x"}), "`where` names"),
    (_item("Plan", kind="reverse", entity=SUB, via="shopperId", sort="nope"), "`sort` names"),
    (_item("Plan", kind="reverse", entity=SUB, via="shopperId",
           then={"via": "nope", "entity": PLAN}), "`then.via` must be a foreign key"),
    (_item("Plan", kind="reverse", entity=SUB, via="shopperId",
           then={"via": "planId", "entity": SHOPPER}), "references ENTITY-010, not ENTITY-001"),
    (_item("Plan", kind="reverse", entity=SUB, via="shopperId",
           then={"via": "planId", "entity": PLAN, "field": "price"}), "Plan has no field 'price'"),
    (_item("Active", kind="count", entity=SUB, of="planId"), "name `via` too"),
])
def test_a_reverse_source_that_does_not_resolve_is_named(item, fault):
    findings = content_findings(_page(item), _doc())
    assert findings and fault in findings[0], findings


def test_a_forward_link_that_is_stored_on_the_other_side_points_at_reverse():
    """The refusal the HippieKit author kept hitting now says what to use."""
    item = _item("Current plan", kind="related", entity=PLAN, via="planId")
    (finding,) = content_findings(_page(item), _doc())
    assert "use `reverse`" in finding


def test_a_field_the_far_record_lacks_is_requested_on_it():
    item = _item("Plan price", kind="reverse", entity=SUB, via="shopperId",
                 then={"via": "planId", "entity": PLAN, "field": "price"},
                 newField={"type": "decimal", "description": "Monthly price"})
    doc = _doc()
    doc["pages"] = [_page(item)]
    assert content_findings(doc["pages"][0], doc) == []
    assert [f["name"] for f in requested_fields(doc)[PLAN]] == ["price"]


def test_the_engineer_gets_the_read_for_each():
    doc = _doc()
    brief = {b["label"]: b["read"] for b in content_brief(doc, _page(CURRENT_PLAN, RENEWAL))}
    row = ('(await list("Subscription", { where: { shopperId: shopper.id, status: \'active\' }, '
           'sort: "createdAt", order: "desc", limit: 1 }))[0]')
    assert brief["Current plan"] == f'(await record("Plan", {row}?.planId))?.name'
    assert brief["Renews on"] == f"{row}?.renewalDate"
    staff = {b["label"]: b["read"] for b in content_brief(
        doc, _page(ACTIVE, EVERYONE, route="/staff/subscribers", primary=None))}
    assert staff == {"Active": "count(\"Subscription\", { status: 'active' })",
                     "Total subscribers": 'count("Subscription")'}


def test_the_contract_and_the_author_know_both():
    schema = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json").read_text())
    text = json.dumps(schema)
    assert '"reverse"' in text and '"then"' in text
    from services.blueprint.executors import NODE_TASKS
    prompt = NODE_TASKS["page_details"]
    assert "`reverse`" in prompt and "Leave `via` out to count every" in prompt


# --- a count through a join ---------------------------------------------------
#
# HippieKit's rebuild (2026-09-22) retried a product page on "Harmful
# ingredients": ProductIngredient rows whose Ingredient is of kind harmful.
# `where` only named the counted entity's own fields.

PRODUCT, INGREDIENT, LINK = "ENTITY-003", "ENTITY-006", "ENTITY-005"


def _join_doc():
    return {"data": {"entities": [
        {"id": PRODUCT, "name": "Product", "fields": [{"name": "id", "type": "uuid"}]},
        {"id": INGREDIENT, "name": "Ingredient", "fields": [
            {"name": "id", "type": "uuid"}, {"name": "kind", "type": "enum", "enumValues": ["clean", "harmful"]}]},
        # The link's keys carry no `references`: the relationship says where they point.
        {"id": LINK, "name": "ProductIngredient", "fields": [
            {"name": "id", "type": "uuid"}, {"name": "productId", "type": "uuid"},
            {"name": "ingredientId", "type": "uuid"}]}],
        "relationships": [
            {"from": PRODUCT, "to": LINK, "kind": "one_to_many", "fromField": "id", "toField": "productId"},
            {"from": INGREDIENT, "to": LINK, "kind": "one_to_many", "fromField": "id", "toField": "ingredientId"}]},
        "pages": []}


HARMFUL = _item("Harmful ingredients", kind="count", entity=LINK, via="productId",
                where={"ingredientId.kind": "harmful"})


def test_a_count_may_filter_on_the_record_a_foreign_key_points_at():
    assert content_findings(_page(HARMFUL, route="/products/[id]", primary=PRODUCT), _join_doc()) == []


@pytest.mark.parametrize("where, fault", [
    ({"ingredient.kind": "harmful"}, "before the dot goes a foreign key of ProductIngredient (productId, ingredientId)"),
    ({"ingredientId.colour": "red"}, "Ingredient has no field 'colour'"),
])
def test_a_join_that_does_not_resolve_says_how_to_write_it(where, fault):
    item = _item("Harmful", kind="count", entity=LINK, via="productId", where=where)
    (finding,) = content_findings(_page(item, route="/products/[id]", primary=PRODUCT), _join_doc())
    assert fault in finding, finding


def test_a_reverse_fact_filters_on_its_own_fields_only():
    """`reverse` reads through `list`, which filters on the entity's own columns."""
    item = _item("Latest harmful", kind="reverse", entity=LINK, via="productId",
                 where={"ingredientId.kind": "harmful"})
    (finding,) = content_findings(_page(item, route="/products/[id]", primary=PRODUCT), _join_doc())
    assert "own fields only" in finding


def test_the_engineer_is_given_the_target_by_name():
    """The generated app does not know where a foreign key points; the read says."""
    doc = _join_doc()
    (b,) = content_brief(doc, _page(HARMFUL, route="/products/[id]", primary=PRODUCT))
    assert b["read"] == ('count("ProductIngredient", { productId: product.id, '
                         'ingredientId: { in: "Ingredient", where: { kind: \'harmful\' } } })')


def test_the_sdk_and_the_engine_speak_the_same_join():
    root = Path(__file__).resolve().parents[2]
    sdk = (root / "templates" / "app-foundation" / "src" / "sdk" / "server.ts").read_text()
    engine = (root / "templates" / "runtime" / "data-engine.ts").read_text()
    samples = (root / "static" / "jit-samples.mjs").read_text()
    assert "export type CountWhere" in sdk and "where?: CountWhere<E>" in sdk
    assert "async function joinedCondition" in engine and "accessConditions(targetName" in engine
    assert "rel.in" in samples
