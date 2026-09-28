"""SnapIT (forge-v3 ho6irnp6), 2026-09-29: "Persist matched, verified
listings: ParseError: Unexpected token after expression: Identifier ("each")".

Three `custom` steps carried a paragraph of instructions as their `code`
("For each deduplicated listing … upsert a Merchant …"). The engine evaluates
`code` as one FEEL formula; the author's check parsed only conditions, and
the catalog called the node "Execute custom logic".
"""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import (AgentResult, ArtifactProposal, InvalidWorkflowStep,
                                               check_workflow_steps)
from services.blueprint.functional_completeness import expression_findings
from services.catalog import workflow_nodes

PROSE = ("For each deduplicated listing in extract_listings.output: upsert a Merchant by domain, "
         "insert a PriceHistory row for it")


def _doc(*steps):
    return {"workflows": [{"id": "FLOW-001", "name": "Identify Product From Snap", "steps": list(steps)}],
            "businessRules": []}


def _custom(key, code, action="custom"):
    return {"key": key, "type": "action", "config": {"actionType": action, "code": code}}


def test_instructions_in_words_are_refused_with_the_way_out():
    found = expression_findings(_doc(_custom("persist_listings", PROSE)))
    assert len(found) == 1
    detail = found[0]["detail"]
    assert "Identify Product From Snap, step 'persist_listings'" in detail
    assert "ONE FEEL formula" in detail and "`ai_generate` or `ai_extract`" in detail
    assert "`aiExtractMany: true`" in detail and "one `db_insert` whose `values` carry that whole list" in detail


def test_a_transform_is_held_to_the_same():
    assert expression_findings(_doc(_custom("shape", "Map each listing to a row", "transform")))


def test_a_real_formula_passes():
    assert expression_findings(_doc(_custom("any_found", "count(listings) > 0"))) == []


def test_a_comment_and_an_empty_code_are_not_formulas():
    assert expression_findings(_doc(_custom("a", "// placeholder"), _custom("b", ""))) == []


def test_conditions_are_still_checked_as_before():
    bad = {"key": "check", "type": "condition", "config": {"expression": "status == \"A\""}}
    assert "Conditions are FEEL" in expression_findings(_doc(bad))[0]["detail"]


def test_the_contract_sends_it_back_to_the_author():
    body = {"name": "Identify Product From Snap", "trigger": {"kind": "manual"},
            "steps": [{"key": "trigger", "type": "trigger", "name": "Start", "config": {"type": "manual"},
                       "next": ["persist_listings"]},
                      {**_custom("persist_listings", PROSE), "name": "Persist", "next": []}]}
    result = AgentResult(task_id="t", agent="workflow_steps", proposals=[
        ArtifactProposal(section="workflows", natural_key="Identify Product From Snap", body=body)])
    with pytest.raises(InvalidWorkflowStep) as e:
        check_workflow_steps(result, {"data": {"entities": []}})
    assert "cannot parse" in str(e.value) and "each" in str(e.value)


def test_the_author_is_told_what_code_is():
    digest = workflow_nodes().digest()
    assert "custom — Evaluate ONE FEEL formula" in digest
    from services.blueprint.executors import NODE_TASKS
    assert "step's `code` is ONE FEEL formula" in NODE_TASKS["workflow_steps"]


# ── Many records: a list from ai_extract, saved one row per item ────────────

def _entities():
    return {"entities": [{"name": "SearchResult", "table": "search_results", "fields": [
        {"name": "id", "primaryKey": True}, {"name": "searchId", "required": True},
        {"name": "title", "required": True}, {"name": "url", "required": True},
        {"name": "matchScore", "required": True}]}]}


def _listing_flow(fields, many=True):
    return {"id": "FLOW-001", "name": "Identify Product From Snap", "steps": [
        {"key": "extract_listings", "type": "ai_extract",
         "config": {"aiExtractMany": many, "aiExtractFields": fields, "aiInput": "{{crawl_listings.output}}"}},
        {"key": "save_results", "type": "action", "config": {
            "actionType": "db_insert", "table": "search_results",
            "values": {"searchId": "{{create_search.id}}", "rows": "{{extract_listings.output}}"}}}]}


def test_a_list_supplies_the_fields_its_items_carry():
    from services.blueprint.functional_completeness import column_findings, insert_findings
    doc = {"data": _entities(), "workflows": [_listing_flow(["title", "url", "matchScore"])]}
    assert insert_findings(doc) == [] and column_findings(doc) == []


def test_a_list_that_lacks_a_required_field_is_named():
    from services.blueprint.functional_completeness import insert_findings
    doc = {"data": _entities(), "workflows": [_listing_flow(["title"])]}
    assert "without 'url', 'matchScore'" in insert_findings(doc)[0]["detail"]


def test_one_record_is_not_a_list():
    from services.blueprint.functional_completeness import column_findings, insert_findings
    doc = {"data": _entities(), "workflows": [_listing_flow(["title", "url", "matchScore"], many=False)]}
    assert insert_findings(doc) and "'rows'" in column_findings(doc)[0]["detail"]


def test_the_author_is_told_how_many_records_are_saved():
    from services.blueprint.executors import NODE_TASKS
    assert "`aiExtractMany: true`" in NODE_TASKS["workflow_steps"]
    assert "aiExtractMany: true a list of every record" in workflow_nodes().digest()
