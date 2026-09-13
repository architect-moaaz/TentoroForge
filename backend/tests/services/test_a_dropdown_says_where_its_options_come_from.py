"""A dropdown's option source arrives in the contract's words, with its list.

The composer writes `optionsFrom: {entity, labelField, valueField}` — entity
first, as it thinks about data — on a declarative Form field or a Select. The
Form field schema reads `interaction.optionsFrom: {source, value, label}` and
the Select contract reads `optionsFrom: {source, …}` with no empty `options`
beside it. Every intake form on one real build was refused over the
difference, while the page's data sources held nothing that listed the
entity. Translation registers the list and names it.
"""
import json

from services.a2ui_to_forge import translate
from services.blueprint.page_planner import load_catalog, validate_props

REG = {"entities": {
    "RefundCase": {"slug": "refund-cases", "camel": "refundCase", "columns": [
        {"name": "id", "type": "uuid"}, {"name": "propertyId", "type": "uuid", "references": "Property"},
        {"name": "guestName", "type": "varchar"}, {"name": "source", "type": "varchar"}]},
    "Property": {"slug": "properties", "camel": "property", "columns": [
        {"name": "id", "type": "uuid"}, {"name": "name", "type": "varchar"}, {"name": "shortCode", "type": "varchar"}]},
}, "pageEntity": {"PAGE-007": "RefundCase"}, "workflows": [],
   "entityNames": {"ENTITY-001": "Property", "ENTITY-003": "RefundCase"}}


def _payload(comps):
    return {"messages": [{"version": "v0.9", "updateDataModel": {"value": {}}},
                         {"version": "v0.9", "updateComponents": {"components": comps}}]}


def _find(node, kind):
    if node.get("type") == kind:
        return node
    for c in node.get("children") or []:
        hit = _find(c, kind)
        if hit:
            return hit
    return None


def test_a_declared_field_naming_an_entity_id_gets_a_source_and_its_list():
    comps = [{"id": "root", "component": "Stack", "children": ["form"]},
             {"id": "form", "component": "Form", "workflow": "FLOW-001", "submitLabel": "Create",
              "fields": [{"kind": "select", "name": "propertyId", "label": "Property", "required": True,
                          "optionsFrom": {"entity": "ENTITY-001", "labelField": "name", "valueField": "id"}},
                         {"kind": "text", "name": "guestName", "label": "Guest"}]}]
    schema = translate(_payload(comps), REG, route="/refund-cases/new", page_id="PAGE-007")["schema"]
    field = _find(schema["root"], "Form")["props"]["fields"][0]
    assert "optionsFrom" not in field
    assert field["interaction"]["optionsFrom"] == {"source": "properties", "value": "id", "label": "name"}
    assert {"name": "properties", "entity": "Property", "op": "list"} in schema["dataSources"]


def test_the_translated_form_satisfies_the_contract():
    comps = [{"id": "root", "component": "Stack", "children": ["form"]},
             {"id": "form", "component": "Form", "workflow": "FLOW-001", "submitLabel": "Create",
              "fields": [{"kind": "select", "name": "propertyId", "label": "Property", "required": True,
                          "optionsFrom": {"entity": "Property", "labelField": "name"}}]}]
    schema = translate(_payload(comps), REG, route="/refund-cases/new", page_id="PAGE-007")["schema"]
    form = _find(schema["root"], "Form")
    problems = validate_props({"root": form}, load_catalog())
    assert problems == [], problems


def test_a_select_named_after_a_foreign_key_keeps_its_source():
    comps = [{"id": "root", "component": "Stack", "children": ["form"]},
             {"id": "form", "component": "Form", "workflow": "FLOW-001", "submitLabel": "Create", "children": ["sel"]},
             {"id": "sel", "component": "Select", "name": "propertyId", "label": "Property", "options": [],
              "optionsFrom": {"entity": "Property", "labelField": "name", "valueField": "id"}}]
    schema = translate(_payload(comps), REG, route="/refund-cases/new", page_id="PAGE-007")["schema"]
    sel = _find(schema["root"], "Select")
    assert sel["props"]["optionsFrom"] == {"source": "properties", "value": "id", "label": "name"}
    assert "options" not in sel["props"]
    assert validate_props({"root": sel}, load_catalog()) == []


def test_a_foreign_key_select_with_nothing_said_still_gets_its_list():
    comps = [{"id": "root", "component": "Stack", "children": ["form"]},
             {"id": "form", "component": "Form", "workflow": "FLOW-001", "submitLabel": "Create", "children": ["sel"]},
             {"id": "sel", "component": "Select", "name": "propertyId", "label": "Property"}]
    schema = translate(_payload(comps), REG, route="/refund-cases/new", page_id="PAGE-007")["schema"]
    sel = _find(schema["root"], "Select")
    assert sel["props"]["optionsFrom"]["source"] == "properties"


def test_items_named_by_label_alone_take_it_as_their_value():
    from services.a2ui_to_forge import _translate_option_sources, _Binder
    root = {"type": "Stack", "props": {}, "children": [
        {"type": "Tabs", "props": {"items": [{"label": "Front desk"}, {"label": "Guest", "value": "guest"}]}, "children": []}]}
    _translate_option_sources(root, _Binder(REG, {}), REG)
    assert [i["value"] for i in root["children"][0]["props"]["items"]] == ["Front desk", "guest"]


def test_a_placeholder_option_becomes_the_placeholder():
    """/support-cases/new was refused for `options.0.value: '' should be
    non-empty`: the composer wrote the empty select's caption as an option."""
    from services.a2ui_to_forge import _translate_option_sources, _Binder
    root = {"type": "Form", "props": {"fields": [
        {"kind": "select", "name": "caseType", "label": "Type",
         "options": [{"label": "Select a type", "value": ""}, {"label": "Complaint", "value": "COMPLAINT"}]}]},
        "children": [{"type": "Select", "props": {"name": "priority", "options": [
            {"label": "Choose…", "value": ""}, {"label": "High", "value": "HIGH"}]}, "children": []}]}
    _translate_option_sources(root, _Binder(REG, {}), REG)
    field = root["props"]["fields"][0]
    assert field["options"] == [{"label": "Complaint", "value": "COMPLAINT"}]
    assert field["placeholder"] == "Select a type"
    sel = root["children"][0]["props"]
    assert sel["options"] == [{"label": "High", "value": "HIGH"}] and sel["placeholder"] == "Choose…"
