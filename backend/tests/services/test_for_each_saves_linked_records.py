"""SnapIT (forge-v3 ho6irnp6), 2026-09-29: each listing found needs a
merchant, a merchant product pointing at it, and a search result pointing at
both. The engine had no per-item step, so the photo search could not save
anything; `for_each` runs steps once per item, and every check holds the
steps inside it to the same rules as any other."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import (AgentResult, ArtifactProposal, InvalidWorkflowStep,
                                               check_workflow_steps)
from services.blueprint.functional_completeness import (authoring_findings, loop_step_errors,
                                                        with_loop_bodies)
from services.catalog import workflow_nodes

DATA = {"entities": [
    {"name": "Merchant", "table": "merchants", "fields": [
        {"name": "id", "primaryKey": True}, {"name": "domain", "required": True}, {"name": "name", "required": True}]},
    {"name": "MerchantProduct", "table": "merchant_products", "fields": [
        {"name": "id", "primaryKey": True}, {"name": "merchantId", "required": True}, {"name": "url", "required": True}]},
    {"name": "SearchResult", "table": "search_results", "fields": [
        {"name": "id", "primaryKey": True}, {"name": "searchId", "required": True},
        {"name": "merchantProductId", "required": True}, {"name": "matchScore", "required": True}]},
]}


def _flow(inner=None, items="{{extract_listings.output}}"):
    inner = inner if inner is not None else [
        {"key": "merchant", "config": {"actionType": "db_insert", "table": "merchants", "findBy": ["domain"],
                                       "values": {"domain": "{{listing.domain}}", "name": "{{listing.seller}}"}}},
        {"key": "merchant_product", "config": {"actionType": "db_insert", "table": "merchant_products",
                                               "values": {"merchantId": "{{merchant.id}}", "url": "{{listing.url}}"}}},
        {"key": "result", "config": {"actionType": "db_insert", "table": "search_results",
                                     "values": {"searchId": "{{create_search.id}}",
                                                "merchantProductId": "{{merchant_product.id}}",
                                                "matchScore": "{{listing.matchScore}}"}}},
    ]
    return {"id": "FLOW-001", "name": "Identify Product From Snap", "trigger": {"kind": "manual"}, "inputs": [],
            "steps": [
                {"key": "trigger", "type": "trigger", "name": "Start", "config": {"type": "manual"},
                 "next": ["create_search"]},
                {"key": "create_search", "type": "action", "name": "Create search", "next": ["extract_listings"],
                 "config": {"actionType": "db_insert", "table": "searches", "values": {"status": "open"}}},
                {"key": "extract_listings", "type": "ai_extract", "name": "Extract", "next": ["save_listings"],
                 "config": {"aiExtractMany": True, "aiExtractFields": ["domain", "seller", "url", "matchScore"],
                            "aiInput": "{{create_search.id}}"}},
                {"key": "save_listings", "type": "action", "name": "Save each listing", "next": [],
                 "config": {"actionType": "for_each", "items": items, "as": "listing", "steps": inner}},
            ]}


def _doc(flow):
    return {"data": DATA, "workflows": [flow], "businessRules": []}


def test_the_catalog_has_the_step():
    assert workflow_nodes().missing("action", {"actionType": "for_each"}) == ["items", "steps"]
    assert "for_each — Run steps once per item" in workflow_nodes().digest()


def test_a_loop_is_read_as_its_steps_in_order():
    keys = [s["key"] for s in with_loop_bodies(_flow())["steps"]]
    assert keys[3:] == ["save_listings", "__save_listings_listing", "__save_listings_listingIndex",
                        "merchant", "merchant_product", "result"]


def test_a_well_written_loop_passes_every_check():
    assert authoring_findings(_doc(_flow())) == []


def test_an_inner_insert_missing_a_required_field_is_named():
    flow = _flow()
    flow["steps"][3]["config"]["steps"][1]["config"]["values"].pop("url")
    details = " | ".join(f["detail"] for f in authoring_findings(_doc(flow)))
    assert "step 'merchant_product': inserts into MerchantProduct without 'url'" in details


def test_an_inner_step_reading_nothing_is_named():
    flow = _flow()
    flow["steps"][3]["config"]["steps"][2]["config"]["values"]["merchantProductId"] = "{{product.id}}"
    assert any("{{product.id}}" in f["detail"] for f in authoring_findings(_doc(flow)))


def test_the_item_is_not_read_outside_its_loop():
    """`listing` is the loop's; a step reading it is held to the same check,
    and inside the loop it is known."""
    flow = _flow()
    assert not any("listing" in f["detail"] for f in authoring_findings(_doc(flow)))


def test_a_loop_with_no_steps_or_a_loop_inside_is_refused():
    assert "it has none" in loop_step_errors(_flow(inner=[]))[0]
    nested = _flow(inner=[{"key": "again", "config": {"actionType": "for_each", "items": "{{x}}", "steps": []}}])
    assert "inside a for_each" in loop_step_errors(nested)[0]


def test_the_contract_holds_inner_actions_to_the_catalog():
    flow = _flow(inner=[{"key": "merchant", "config": {"actionType": "db_insert", "values": {"domain": "x"}}}])
    result = AgentResult(task_id="t", agent="workflow_steps", proposals=[
        ArtifactProposal(section="workflows", natural_key=flow["name"], body=flow)])
    with pytest.raises(InvalidWorkflowStep) as e:
        check_workflow_steps(result, {"data": DATA})
    assert "save_listings/merchant: config needs one of: table" in str(e.value)


def test_the_author_is_told_when_to_loop_and_how_to_find_or_create():
    from services.blueprint.executors import NODE_TASKS
    text = NODE_TASKS["workflow_steps"]
    assert "it is one `for_each` action" in text and "`findBy: [the columns that identify it]`" in text


def test_a_where_that_does_not_parse_is_named():
    flow = _flow()
    flow["steps"][3]["config"]["where"] = "listing.price != null and"
    assert any("save_listings" in f["detail"] and "cannot parse" in f["detail"]
               for f in authoring_findings(_doc(flow)))
    flow["steps"][3]["config"]["where"] = "listing.price != null"
    assert authoring_findings(_doc(flow)) == []


def test_signup_completes_the_login_row_when_the_account_lives_in_it():
    """SnapIT's account entity is "User" on the platform's `users` table; a
    second insert there had no password and every signup failed."""
    from pathlib import Path
    route = (Path(__file__).resolve().parents[2] / "templates/app-foundation/src/app/api/auth/signup/route.ts").read_text()
    assert "(accountTable as unknown) === (users as unknown)" in route
    assert "tx.update(users).set(own as any).where(eq(users.id, created.id))" in route
    assert '!["id", "email", "password"].includes(k)' in route
