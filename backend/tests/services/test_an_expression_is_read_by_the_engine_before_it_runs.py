"""A condition the engine cannot parse is refused when it is authored.

`{{input.caseType}} == 'REFUND' && …` reached a real workflow, the "Create
Case" form dispatched it, the engine answered 200, and no case was written:
the tokenizer refused `==` at run time. The check runs the engine's own
tokenizer and parser over every workflow condition and rule condition, so
what it refuses is exactly what the engine would.
"""
import shutil

import pytest

from services.blueprint.feel_check import check_expressions
from services.blueprint.functional_completeness import functional_findings

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node is the engine's language")


@needs_node
def test_javascript_is_refused_and_feel_is_not():
    errors = check_expressions([
        ("js", "{{input.caseType}} == 'REFUND' && {{input.refundAmount}} > 0"),
        ("feel", 'input.caseType = "Refund" and input.refundAmount > 0'),
    ])
    assert "js" in errors and "Eq" in errors["js"] or "=" in errors.get("js", "")
    assert "feel" not in errors


@needs_node
def test_a_workflow_with_a_javascript_condition_is_refused_with_the_dialect():
    doc = {"data": {"entities": []}, "businessRules": [], "pages": [], "pageLayouts": [],
           "workflows": [{"id": "FLOW-016", "name": "Create Case", "steps": [
               {"key": "needs_approval", "type": "condition",
                "config": {"expression": "{{input.caseType}} == 'REFUND' && {{input.refundAmount}} > 0"}}]}]}
    found = [f for f in functional_findings(doc) if f["rule"] == "expression-invalid"]
    assert found and "Create Case, step 'needs_approval'" in found[0]["detail"] and "`=` not `==`" in found[0]["detail"]


@needs_node
def test_a_rule_condition_is_checked_too():
    doc = {"data": {"entities": [{"id": "E1", "name": "Case", "fields": [{"name": "caseType"}]}]}, "pages": [], "pageLayouts": [], "workflows": [],
           "businessRules": [{"id": "RULE-1", "name": "R", "statement": "s", "kind": "condition_action", "entity": "E1",
                              "when": "caseType == 'Refund'", "then": [{"type": "set_required", "field": "caseType"}]}]}
    assert any(f["rule"] == "expression-invalid" and "rule R" in f["detail"] for f in functional_findings(doc))


@needs_node
def test_a_valid_condition_passes():
    doc = {"data": {"entities": []}, "businessRules": [], "pages": [], "pageLayouts": [],
           "workflows": [{"id": "FLOW-1", "name": "W", "steps": [{"key": "c", "type": "condition", "config": {"expression": 'input.caseType = "Refund"'}}]}]}
    assert not [f for f in functional_findings(doc) if f["rule"] == "expression-invalid"]


def test_without_node_nothing_is_invented(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    assert check_expressions([("x", "a == b")]) == {}


# ---------------------------------------------------------------- templates

from services.blueprint.functional_completeness import template_findings  # noqa: E402


def _wf(steps, inputs=("title", "caseType")):
    return {"data": {"entities": []}, "businessRules": [], "pages": [], "pageLayouts": [],
            "workflows": [{"id": "FLOW-016", "name": "Create Case",
                           "inputs": [{"name": n, "kind": "field"} for n in inputs], "steps": steps}]}


def test_the_engines_roots_pass():
    doc = _wf([{"key": "allocate_ref", "type": "action", "config": {"actionType": "set_variable", "variableName": "caseNumber", "value": "CASE-{{title}}"}},
               {"key": "insert_case", "type": "action", "config": {"actionType": "db_insert", "table": "cases",
                                                                     "values": {"title": "{{title}}", "case_number": "{{caseNumber}}", "created_by_id": "$user.id", "opened_at": "$now"}}},
               {"key": "audit", "type": "action", "config": {"actionType": "db_insert", "table": "case_activities", "values": {"case_id": "{{insert_case.id}}"}}}])
    assert template_findings(doc) == []


def test_invented_roots_are_refused_with_the_engines_spelling():
    doc = _wf([{"key": "insert_case", "type": "action", "config": {"actionType": "db_insert", "table": "cases", "values": {
        "case_type": "{{input.caseType}}", "approval_state": "{{vars.approvalState}}", "created_at": "{{now}}", "created_by_id": "{{currentUser.id}}"}}},
        {"key": "audit", "type": "action", "config": {"actionType": "db_insert", "table": "case_activities", "values": {"case_id": "{{steps.insert_case.output.id}}"}}}])
    details = [f["detail"] for f in template_findings(doc)]
    assert any("{{input.caseType}}" in d and "`{{title}}`, not `{{input.title}}`" in d for d in details)
    assert any("{{vars.approvalState}}" in d and "variable name alone" in d for d in details)
    assert any("{{now}}" in d and "`$now`" in d for d in details)
    assert any("{{currentUser.id}}" in d and "`$user.id`" in d for d in details)
    assert any("{{steps.insert_case.output.id}}" in d and "`{{insert_case.id}}`" in d for d in details)


def test_an_unknown_name_lists_what_is_known():
    doc = _wf([{"key": "s", "type": "action", "config": {"actionType": "db_insert", "table": "cases", "values": {"x": "{{guestName}}"}}}])
    (f,) = template_findings(doc)
    assert "{{guestName}}" in f["detail"] and "caseType, title" in f["detail"]


def test_findings_reach_the_composer_and_verification():
    doc = _wf([{"key": "s", "type": "action", "config": {"values": {"x": "{{now}}"}}}])
    assert any(f["rule"] == "template-unknown" for f in functional_findings(doc))


def test_a_function_the_engine_lacks_is_refused_with_the_table_it_has():
    from services.blueprint.feel_check import check_expressions
    errors = check_expressions([("a", 'concat("CASE-", substring(string(uuid()), 1, 8))'), ("b", 'string(refundAmount)')])
    assert "b" not in errors
    assert "concat" in errors["a"] and "the engine has sum, count" in errors["a"]


# ------------------------------------------------------------ who is refused

def test_a_workflows_fault_refuses_the_workflow_not_the_pages():
    from services.blueprint.functional_completeness import page_findings, authoring_findings
    doc = _wf([{"key": "s", "type": "action", "config": {"actionType": "set_variable", "variableName": "ref",
                                                          "expression": 'concat("CASE-", title)'}}])
    doc["pages"] = [{"id": "PAGE-001", "route": "/cases"}]
    doc["pageLayouts"] = [{"page": "PAGE-001", "root": {"type": "Stack", "children": []}}]
    assert page_findings(doc) == []
    assert any(f["rule"] == "expression-invalid" and "concat" in f["detail"] for f in authoring_findings(doc))


def test_the_workflow_author_is_refused_at_the_author():
    from types import SimpleNamespace
    from services.blueprint.agent_contract import check_workflow_steps, InvalidWorkflowStep
    body = _wf([{"key": "insert_case", "type": "action", "config": {"actionType": "db_insert", "table": "cases",
                                                                  "values": {"created_at": "{{now}}"}}}])["workflows"][0]
    result = SimpleNamespace(proposals=[SimpleNamespace(section="workflows", body=body, natural_key="FLOW-016")])
    with pytest.raises(InvalidWorkflowStep, match=r"\{\{now\}\}.*\$now"):
        check_workflow_steps(result)


def test_the_rule_author_is_refused_at_the_author():
    from types import SimpleNamespace
    from services.blueprint.agent_contract import check_business_rules, InvalidBusinessRule
    doc = {"data": {"entities": [{"id": "ENT-001", "name": "Case", "fields": [{"name": "caseType"}]}]}}
    rule = {"id": "BR-001", "name": "Refund needs approval", "kind": "condition_action", "entity": "ENT-001",
            "when": 'caseType == "REFUND" && refundAmount > 0', "then": []}
    result = SimpleNamespace(proposals=[SimpleNamespace(section="businessRules", body=rule, natural_key="BR-001")])
    with pytest.raises(InvalidBusinessRule):
        check_business_rules(result, doc)
    rule["when"] = 'caseType = "REFUND"'
    check_business_rules(result, doc)


# --------------------------------------------------------------- inserts

def _case_model():
    return {"entities": [{"id": "ENT-001", "name": "Case", "table": "cases", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True, "required": True},
        {"name": "caseNumber", "type": "string", "required": True, "unique": True},
        {"name": "title", "type": "string", "required": True},
        {"name": "status", "type": "enum", "required": True},
        {"name": "openedAt", "type": "timestamp", "required": True},
        {"name": "notes", "type": "text"}]}]}


def test_an_insert_that_omits_a_required_column_is_refused_naming_it():
    from services.blueprint.functional_completeness import insert_findings
    doc = _wf([{"key": "insert_case", "type": "action", "config": {"actionType": "db_insert", "table": "cases",
                                                                  "values": {"title": "{{title}}", "status": "OPEN"}}}])
    doc["data"] = _case_model()
    (f,) = insert_findings(doc)
    assert f["rule"] == "insert-missing-required"
    assert "'caseNumber', 'openedAt'" in f["detail"] and "$uuid" in f["detail"] and "id" not in f["detail"].split("without")[1].split(",")[0]


def test_an_insert_that_supplies_them_passes():
    from services.blueprint.functional_completeness import insert_findings
    doc = _wf([{"key": "insert_case", "type": "action", "config": {"actionType": "db_insert", "table": "cases",
                                                                  "values": {"title": "{{title}}", "status": "OPEN", "caseNumber": "$uuid", "openedAt": "$now"}}}])
    doc["data"] = _case_model()
    assert insert_findings(doc) == []


def test_the_workflow_author_is_refused_for_the_missing_column():
    from types import SimpleNamespace
    from services.blueprint.agent_contract import check_workflow_steps, InvalidWorkflowStep
    body = _wf([{"key": "insert_case", "type": "action", "config": {"actionType": "db_insert", "table": "cases",
                                                                   "values": {"title": "{{title}}"}}}])["workflows"][0]
    result = SimpleNamespace(proposals=[SimpleNamespace(section="workflows", body=body, natural_key="FLOW-016")])
    with pytest.raises(InvalidWorkflowStep, match="caseNumber"):
        check_workflow_steps(result, {"data": _case_model()})


def test_each_proposal_is_blamed_only_for_its_own_expression():
    from services.blueprint.functional_completeness import expression_findings
    doc = {"data": {"entities": []}, "workflows": [], "pages": [], "pageLayouts": [], "businessRules": [
        {"name": "closed", "kind": "condition_action", "when": 'stage != "DRAFT"', "then": []},
        {"name": "broken", "kind": "condition_action", "when": 'stage == "DRAFT" && x', "then": []},
        {"name": "held", "kind": "condition_action", "when": 'status = "HELD"', "then": []},
    ]}
    found = expression_findings(doc)
    assert [f["detail"].split(":")[0] for f in found] == ["rule broken"]
