"""A layout from either composer has its option sources translated before
the contract reads it.

The refund intake form on Criterion Refunds v2 (agent-composed) carried the
property select as `{kind: select, name: propertyId, optionsFrom: {entity:
ENTITY-001, labelField: name, valueField: id}}` and was refused three times:
once by the field schema, and by the record rule that could see no source.
"""
from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidPatternTemplate, check_pattern_templates,
)
from services.blueprint.layout_vocabulary import translate_layout_vocabulary


def _doc():
    return {
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Property", "fields": [
                {"name": "id", "type": "uuid"}, {"name": "name", "type": "string"}]},
            {"id": "ENTITY-003", "name": "RefundCase", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "propertyId", "type": "uuid", "references": "ENTITY-001", "required": True},
                {"name": "guestName", "type": "string", "required": True}]},
        ], "relationships": []},
        "workflows": [{"id": "FLOW-001", "name": "Refund Case Intake", "status": "PROPOSED", "steps": [],
                       "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-007"],
                       "inputs": [{"name": "propertyId", "kind": "field", "type": "uuid", "required": True},
                                  {"name": "guestName", "kind": "field", "type": "string", "required": True}]}],
        "pages": [{"id": "PAGE-007", "route": "/refund-cases/new", "pattern": "form",
                   "data": {"primaryEntity": "ENTITY-003"}}],
        "security": {},
    }


def _refused_form():
    return {"page": "PAGE-007", "dataSources": [], "root": {
        "type": "Container", "props": {}, "children": [{
            "type": "Form", "props": {
                "workflow": "FLOW-001", "submitLabel": "Submit case",
                "fields": [
                    {"kind": "select", "name": "propertyId", "label": "Property", "required": True,
                     "optionsFrom": {"entity": "ENTITY-001", "labelField": "name", "valueField": "id"}},
                    {"kind": "text", "name": "guestName", "label": "Guest name", "required": True}]},
            "children": []}]}}


def _result(body):
    return AgentResult(task_id="t", agent="page_layouts", confidence=0.9,
                       proposals=[ArtifactProposal(section="pageLayouts", natural_key="PAGE-007", body=body)])


def test_the_agents_field_is_translated_and_its_list_registered():
    result = _result(_refused_form())
    translate_layout_vocabulary(result, _doc())
    body = result.proposals[0].body
    field = body["root"]["children"][0]["props"]["fields"][0]
    assert "optionsFrom" not in field
    assert field["interaction"]["optionsFrom"] == {"source": "properties", "value": "id", "label": "name"}
    assert {"name": "properties", "entity": "Property", "op": "list"} in body["dataSources"]


def test_a_list_the_layout_already_reads_is_reused():
    body = _refused_form()
    body["dataSources"] = [{"name": "propertyList", "entity": "Property", "op": "list", "limit": 10}]
    result = _result(body)
    translate_layout_vocabulary(result, _doc())
    field = result.proposals[0].body["root"]["children"][0]["props"]["fields"][0]
    assert field["interaction"]["optionsFrom"]["source"] == "propertyList"
    assert len(result.proposals[0].body["dataSources"]) == 1


def test_the_translated_form_passes_the_contract_and_the_record_rule():
    """A CREATE form choosing a property from a select sends a foreign key.

    The fixture's FLOW-001 declared that input as `property`, `kind: "record"`
    — "the record this control acts on", which fits a Delete button on a
    record page and cannot be written on a create form: a field's value is not
    a data source, so `args: {property: "{{propertyId}}"}` is refused by the
    binding check. `dispatch_contract.dispatch_findings`, which arrived after
    the fixture, refused the form for it. The input is `propertyId`, a field,
    which is what the form sends.
    """
    result = _result(_refused_form())
    doc = _doc()
    translate_layout_vocabulary(result, doc)
    check_pattern_templates(result, doc)   # raises InvalidPatternTemplate if refused


def test_untranslated_it_is_refused_on_both_counts():
    import pytest
    result = _result(_refused_form())
    with pytest.raises(InvalidPatternTemplate) as err:
        check_pattern_templates(result, _doc())
    assert "not valid" in str(err.value) or "Property record" in str(err.value)


def test_the_signed_in_user_is_called_what_the_renderer_calls_them():
    """The interpolation scope is `user: ctx.user`; a queue filtered on
    `{{currentUser.homePropertyId}}` sent an empty filter and showed nothing."""
    body = {"page": "PAGE-002", "dataSources": [
        {"entity": "RefundCase", "name": "queueCases", "op": "list",
         "filter": {"propertyId": "{{currentUser.homePropertyId}}", "status": "Pending approval"}}],
        "root": {"type": "Text", "props": {"content": "Signed in as {{ currentUser.name }}"}, "children": []}}
    result = _result(body)
    translate_layout_vocabulary(result, _doc())
    b = result.proposals[0].body
    assert b["dataSources"][0]["filter"]["propertyId"] == "{{user.homePropertyId}}"
    assert b["root"]["props"]["content"] == "Signed in as {{user.name }}"
