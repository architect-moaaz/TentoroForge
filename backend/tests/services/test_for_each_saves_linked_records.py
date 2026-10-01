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
    {"name": "Search", "table": "searches", "fields": [
        {"name": "id", "primaryKey": True}, {"name": "status"}, {"name": "resultCount"}]},
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


def test_a_template_that_computes_is_refused():
    """`{{count(list_results)}}` reached the database as that text."""
    from services.blueprint.functional_completeness import template_findings
    flow = {"id": "F", "name": "Snap", "inputs": [], "steps": [
        {"key": "list_results", "type": "action", "config": {"actionType": "db_query", "table": "search_results"}},
        {"key": "finalize", "type": "action", "config": {"actionType": "db_update", "table": "searches",
            "values": {"resultCount": "{{count(list_results)}}", "fine": "{{list_results.count}}",
                       "also": "{{ list_results.rows[0].id }}"}}}]}
    found = [f["detail"] for f in template_findings({"workflows": [flow]})]
    assert len(found) == 1 and "{{count(list_results)}} computes" in found[0]


def test_a_run_reply_carries_the_id_of_what_it_created(tmp_path):
    """SnapIT's Snap page opened `result.id`; the reply had only the log, so
    every snap said "identified this snap but the result could not be opened"."""
    from services.runtime_injector import _generate_workflow_api_route
    _generate_workflow_api_route(tmp_path)
    route = (tmp_path / "src/app/api/workflows/[id]/execute/route.ts").read_text()
    assert "out.inserted && typeof out.id === \"string\"" in route
    assert "records: _records" in route and "id: _first" in route
    from services.blueprint.ui_engineer import system_prompt
    assert "result.id is the id of the first record the run created" in system_prompt(
        {"application": {"name": "x"}, "data": {"entities": []}, "pages": [], "workflows": []})


def test_a_task_for_the_person_running_it_is_theirs():
    """SnapIT's "which product?" task was assigned to the text `$user.id`."""
    from pathlib import Path
    engine = (Path(__file__).resolve().parents[2] / "templates/runtime/workflows/engine.ts").read_text()
    assert 'v === "$user.id" ? (((ctx as any).user?.id as string | undefined) ?? v) : v' in engine
    assert "assignee: _who(config.assignee || (config as any).assignTarget" in engine


def test_a_fallback_template_is_checked_side_by_side():
    """`{{analyze_image.brand ?? "Unbranded"}}` — a brand a photo does not show."""
    from services.blueprint.functional_completeness import template_findings
    from services.blueprint.executors import NODE_TASKS
    flow = {"id": "F", "name": "Snap", "inputs": [], "steps": [
        {"key": "analyze_image", "type": "ai_extract", "config": {"aiExtractFields": ["brand"]}},
        {"key": "resolve", "type": "action", "config": {"actionType": "db_insert", "table": "products", "values": {
            "brand": '{{analyze_image.brand ?? "Unbranded"}}', "n": "{{analyze_image.count ?? 0}}"}}}]}
    assert template_findings({"workflows": [flow]}) == []
    flow["steps"][1]["config"]["values"]["bad"] = '{{nowhere.brand ?? "x"}}'
    flow["steps"][1]["config"]["values"]["worse"] = "{{analyze_image.brand ?? count(x)}}"
    found = " | ".join(f["detail"] for f in template_findings({"workflows": [flow]}))
    assert "'nowhere.brand' is neither" in found and "'count(x)' is neither" in found
    assert '`{{analyze_image.brand ?? \\"Unbranded\\"}}`' in NODE_TASKS["workflow_steps"] or \
           '{{analyze_image.brand ?? "Unbranded"}}' in NODE_TASKS["workflow_steps"]
