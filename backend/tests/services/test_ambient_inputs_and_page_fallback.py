"""DEFECT: form/action pages refused (InvalidPatternTemplate) or never composed
end up with NO schema -> blank editor ("No schema at X.json"), 404 preview, and
Smith unable to fix them.

Two parts:
 - Ambient inputs (organisationId, ownerId, ...) are supplied by the runtime
   from the session and declared in `security.ownershipRules`; a Form must not
   be refused for not collecting them. (This half is the senior's
   `_session_filled_fields` on smithv2; the tests here lock the END behaviour.)
 - A page nothing composed still gets an honest, marked fallback schema so the
   route is never blank. (This half is added here: page_planner._fallback_schema
   + the projection keep-existing rule.)
"""
import json
import pytest

from services.blueprint import functional_completeness as fc
from services.blueprint.page_planner import (
    load_catalog, plan_pages, validate_template, validate_props,
    _fallback_schema,
)


# ---------------------------------------------------------------------------
# Ambient inputs the runtime fills from the session are not refused
# ---------------------------------------------------------------------------

def _bare_form(label="Submit", fields=None):
    props = {"label": label}
    if fields is not None:
        props["fields"] = fields
    return {"type": "Form", "props": props, "children": []}


def _doc(input_name, ownership=None):
    doc = {"workflows": [{"id": "FLOW-001", "name": "Create Thing", "inputs": [
        {"name": input_name, "kind": "field", "required": True}]}],
        "data": {"entities": []}}
    if ownership is not None:
        doc["security"] = {"ownershipRules": ownership}
    return doc


@pytest.mark.parametrize("kind", ["scope", "attribution"])
def test_an_ownership_column_is_not_refused_as_a_missing_form_field(kind):
    """organisationId / ownerId are the caller's own tenant and identity — the
    runtime fills them from the session, and `ownershipRules` declares that. A
    Form must not be refused for not collecting them."""
    doc = _doc("organisationId",
               ownership=[{"entity": "E", "column": "organisationId", "kind": kind}])
    form = _bare_form()
    layout = {"root": {"type": "Stack", "children": [form]}}
    assert fc.unsatisfied_inputs(doc, {"id": "P", "route": "/x/new"},
                                 layout, form, "FLOW-001") == []


def test_a_genuine_field_with_no_rule_and_no_form_is_still_required():
    """The fix must not over-skip: a real user field that no ownership rule
    covers and no Form collects is still refused, so a genuinely broken page is
    still caught."""
    doc = _doc("vesselName")   # no ownershipRules
    form = _bare_form()
    layout = {"root": {"type": "Stack", "children": [form]}}
    missing = fc.unsatisfied_inputs(doc, {"id": "P"}, layout, form, "FLOW-001")
    assert missing and "vesselName" in missing[0]


def test_a_form_that_collects_the_real_field_composes_even_with_an_ambient_one():
    """The MaritimeTalent case: a Form collects the user field (vesselName) but
    not the ambient organisationId (a `scope` ownership column). Before, the
    ambient field refused the whole page; now it composes."""
    doc = {"workflows": [{"id": "FLOW-001", "name": "Create Vessel Profile", "inputs": [
        {"name": "organisationId", "kind": "field", "required": True},
        {"name": "vesselName", "kind": "field", "required": True}]}],
        "data": {"entities": []},
        "security": {"ownershipRules": [{"entity": "E", "column": "organisationId", "kind": "scope"}]}}
    form = _bare_form("Submit Crew Request", fields=[{"name": "vesselName", "label": "Vessel name"}])
    layout = {"root": {"type": "Stack", "children": [form]}}
    assert fc.unsatisfied_inputs(doc, {"id": "P", "route": "/crew-request/new"},
                                 layout, form, "FLOW-001") == []


def test_a_non_required_input_is_never_checked():
    doc = {"workflows": [{"id": "FLOW-001", "name": "W", "inputs": [
        {"name": "vesselName", "kind": "field", "required": False}]}], "data": {"entities": []}}
    form = _bare_form()
    layout = {"root": {"type": "Stack", "children": [form]}}
    assert fc.unsatisfied_inputs(doc, {"id": "P"}, layout, form, "FLOW-001") == []


# ---------------------------------------------------------------------------
# A page nothing composed gets a valid, marked fallback (never blank)
# ---------------------------------------------------------------------------

_CATALOG = load_catalog()


def test_fallback_schema_is_valid_and_marked():
    page = {"id": "PAGE-007", "name": "Add a Pet", "route": "/pets/new",
            "pattern": "form", "module": "MODULE-001", "purpose": "Register a new pet."}
    fb = _fallback_schema({}, page)
    assert fb["meta"]["fallback"] is True
    assert fb["id"] == "PAGE-007" and fb["route"] == "/pets/new"
    assert fb["meta"]["name"] == "Add a Pet"
    errs = validate_template({"root": fb["root"], "pattern": "form"}, _CATALOG)
    errs += validate_props({"root": fb["root"]}, _CATALOG)
    assert errs == []
    # It dispatches no workflow, so it can never be an unsatisfiable template.
    body = json.dumps(fb)
    assert "dispatch" not in body and "workflow" not in body.lower()


def test_fallback_uses_the_route_when_the_page_has_no_name():
    fb = _fallback_schema({}, {"id": "P", "route": "/thing"})
    assert fb["meta"]["name"] == "/thing"


def _page(pid, route, pattern="form"):
    return {"id": pid, "name": route.strip("/") or "Home", "route": route,
            "pattern": pattern, "module": "MODULE-001", "purpose": f"The {route} screen."}


def test_plan_pages_never_leaves_a_declared_page_without_a_schema():
    doc = {"pages": [_page("PAGE-001", "/a"), _page("PAGE-002", "/b"),
                     _page("PAGE-003", "/c")],
           "pageLayouts": [{"page": "PAGE-002",
                            "root": {"type": "Stack", "props": {}, "children": []}}]}
    res = plan_pages(doc, _CATALOG)
    assert set(res["planned"]) == {"PAGE-001", "PAGE-002", "PAGE-003"}
    assert res["planned"]["PAGE-002"]["meta"].get("fallback") in (None, False)
    assert res["planned"]["PAGE-001"]["meta"]["fallback"] is True
    assert res["planned"]["PAGE-003"]["meta"]["fallback"] is True
    assert set(res["fellBack"]) == {"PAGE-001", "PAGE-003"}
    assert {s["page"] for s in res["skipped"]} == {"PAGE-001", "PAGE-003"}


def test_a_broken_template_is_reported_not_masked_by_a_fallback():
    """A template that FAILS to plan (a real authoring error) is reported in
    `failed` and left WITHOUT a schema — §76 keeps a genuine bug visible. The
    fallback is only for a page nothing composed, not a broken composition."""
    doc = {"pages": [{"id": "PAGE-001", "name": "X", "route": "/x",
                      "pattern": "entity_list", "module": "M", "data": {}}],
           "pageLayouts": [{"page": "PAGE-001", "pattern": "entity_list",
                            "requires": {"primaryEntity": True},
                            "root": {"type": "Stack", "props": {}, "children": []}}]}
    res = plan_pages(doc, _CATALOG)
    assert "PAGE-001" not in res["planned"]
    assert res["failed"] and res["failed"][0]["page"] == "PAGE-001"
    assert "PAGE-001" not in res["fellBack"]


# ---------------------------------------------------------------------------
# Integration — the real gate (page_findings, what check_pattern_templates uses)
# ---------------------------------------------------------------------------

def _crew_doc(fields):
    return {
        "pages": [{"id": "PAGE-1", "route": "/crew-request/new", "name": "Crew Request", "pattern": "form"}],
        "workflows": [{"id": "FLOW-001", "name": "Create Vessel Profile", "inputs": [
            {"name": "organisationId", "kind": "field", "required": True},
            {"name": "vesselName", "kind": "field", "required": True}]}],
        "data": {"entities": []}, "businessRules": [],
        "security": {"ownershipRules": [{"entity": "E", "column": "organisationId", "kind": "scope"}]},
        "pageLayouts": [{"page": "PAGE-1", "pattern": "form", "root": {
            "type": "Form", "props": {"label": "Submit", "fields": fields,
                                      "action": {"workflow": "FLOW-001"}}, "children": []}}]}


def test_page_findings_lets_an_ambient_input_page_through():
    from services.blueprint.functional_completeness import page_findings
    bad = [x for x in page_findings(_crew_doc([{"name": "vesselName"}]))
           if x["rule"] == "workflow-inputs-unsatisfied"]
    assert bad == []


def test_page_findings_still_flags_a_genuinely_missing_field():
    from services.blueprint.functional_completeness import page_findings
    bad = [x for x in page_findings(_crew_doc([]))
           if x["rule"] == "workflow-inputs-unsatisfied"]
    det = " | ".join(x["detail"] for x in bad)
    assert "vesselName" in det and "organisationId" not in det
