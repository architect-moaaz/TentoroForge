"""A rule the agent authors changes what the form does.

Three breaks, one chain. Generated Forms derived their rules "model" by
stripping a prefix from the workflow id, so `FLOW-002` matched no entity
and no rule ever fired. Blueprint business rules were prose and an
expression, never projected into the runtime; only panel-authored rules
reached it. And the hints stopped at hidden, required and read-only — no
rule could narrow a field's options.

Now a rule declares its kind, entity, condition and effects (the panel's
own DSL); projection writes it beside the panel's rules in the shape the
runtime reads; every Form on a page is named for the page's entity so its
rules are found; `set_options` is an effect; and a rule acting on a field
the entity lacks is refused.
"""
import json
from pathlib import Path

from services.blueprint.functional_completeness import functional_findings
from services.blueprint.projection import project_business_rules
from services.blueprint.record_scope import carry_entity

ENTITIES = [{"id": "ENTITY-002", "name": "Case", "fields": [{"name": "id"}, {"name": "caseType"}, {"name": "amount"}, {"name": "currency"}]}]
RULE = {"id": "RULE-007", "name": "A refund has an amount", "statement": "Refund cases carry an amount.",
        "kind": "condition_action", "entity": "ENTITY-002", "when": 'caseType = "Refund"',
        "then": [{"type": "set_required", "field": "amount", "required": True},
                 {"type": "set_visibility", "field": "currency", "visible": True},
                 {"type": "set_options", "field": "currency", "options": [{"value": "GBP", "label": "£"}, {"value": "EUR", "label": "€"}]}],
        "otherwise": [{"type": "set_visibility", "field": "currency", "visible": False}],
        "scope": "form", "salience": 5}


def _doc(rules):
    return {"data": {"entities": ENTITIES}, "businessRules": rules, "workflows": [], "pages": [], "pageLayouts": []}


def test_the_contract_declares_effects():
    schema = json.dumps(json.loads(Path("contracts/blueprint.schema.json").read_text()))
    assert "condition_action" in schema and "set_options" in schema and '"otherwise"' in schema


def test_the_rule_is_projected_in_the_shape_the_runtime_reads(tmp_path):
    out = project_business_rules(_doc([RULE]), tmp_path)
    rows = json.loads((tmp_path / "rules" / "blueprint-rules.json").read_text())
    assert out["rules"] == 1 and len(rows) == 1
    row = rows[0]
    assert row["rule_type"] == "condition_action" and row["model_name"] == "Case" and row["source"] == "blueprint"
    assert row["config"]["whenFeel"] == 'caseType = "Refund"' and row["config"]["scope"] == "form" and row["config"]["salience"] == 5
    assert [a["type"] for a in row["config"]["then"]] == ["set_required", "set_visibility", "set_options"]
    assert row["config"]["then"][2]["options"][0] == {"value": "GBP", "label": "£"}
    assert row["config"]["otherwise"][0]["visible"] is False
    assert all(a["id"] for a in row["config"]["then"]), "every action carries an id, as the panel's do"


def test_a_statement_only_rule_is_not_projected(tmp_path):
    prose = {"id": "RULE-001", "name": "Be kind", "statement": "Staff are courteous."}
    project_business_rules(_doc([prose, RULE]), tmp_path)
    rows = json.loads((tmp_path / "rules" / "blueprint-rules.json").read_text())
    assert [r["id"] for r in rows] == ["RULE-007"]


def test_the_file_is_written_even_when_empty(tmp_path):
    project_business_rules(_doc([]), tmp_path)
    assert json.loads((tmp_path / "rules" / "blueprint-rules.json").read_text()) == []


def test_every_form_on_a_page_is_named_for_the_pages_entity():
    doc = _doc([RULE]); page = {"data": {"primaryEntity": "ENTITY-002"}}
    root = {"type": "Stack", "props": {}, "children": [
        {"type": "Form", "props": {"workflow": "FLOW-002"}, "children": []},
        {"type": "Form", "props": {"entity": "Other"}, "children": []}]}
    assert carry_entity(doc, page, root) == 1
    assert root["children"][0]["props"]["entity"] == "Case"
    assert root["children"][1]["props"]["entity"] == "Other", "an authored entity is kept"


def test_a_rule_acting_on_a_field_the_entity_lacks_is_refused():
    bad = {**RULE, "then": [{"type": "set_required", "field": "amountDue", "required": True}]}
    rules = [(f["rule"], f["detail"]) for f in functional_findings(_doc([bad]))]
    assert any(r == "rule-field-unknown" and "'amountDue'" in d and "Case does not have" in d for r, d in rules), rules


def test_a_rule_with_effects_and_no_entity_is_refused():
    bad = {**RULE, "entity": "ENTITY-404"}
    assert any(f["rule"] == "rule-without-entity" for f in functional_findings(_doc([bad])))


def test_a_well_formed_rule_passes():
    assert not [f for f in functional_findings(_doc([RULE])) if f["rule"].startswith("rule-")]


def test_the_data_layer_projects_the_rules():
    import inspect
    from services.blueprint import orchestrator
    assert "project_business_rules(svc.doc, app_root)" in inspect.getsource(orchestrator._project_data_layer)


def test_projection_names_every_form():
    import inspect
    from services.blueprint import page_planner
    assert "carry_entity(doc, page, root)" in inspect.getsource(page_planner.plan_page)
