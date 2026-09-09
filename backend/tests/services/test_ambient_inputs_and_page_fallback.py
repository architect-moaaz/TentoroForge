"""DEFECT: form/action pages refused (InvalidPatternTemplate) or never composed
end up with NO schema -> blank editor ("No schema at X.json"), 404 preview, and
Smith unable to fix them.

Two fixes:
 - unsatisfied_inputs no longer refuses inputs the runtime fills from the session
   (tenancy/owner/actor FKs + ownershipRules columns).
 - plan_pages gives a page nothing composed an honest, marked fallback schema so
   the route is never blank; a page that composed before is never overwritten.
"""
import json
import pytest

from services.blueprint import functional_completeness as fc
from services.blueprint.page_planner import (
    load_catalog, plan_pages, validate_template, validate_props,
    _fallback_schema,
)


# ---------------------------------------------------------------------------
# Fix A — runtime-supplied inputs are not refused
# ---------------------------------------------------------------------------

def _wf(name, kind="field", required=True, wid="FLOW-001", wfname="Create Thing"):
    return {"workflows": [{"id": wid, "name": wfname,
                           "inputs": [{"name": name, "kind": kind, "required": required}]}],
            "data": {"entities": []}}


def _bare_form(label="Submit", fields=None):
    props = {"label": label}
    if fields is not None:
        props["fields"] = fields
    return {"type": "Form", "props": props, "children": []}


@pytest.mark.parametrize("name", [
    "organisationId", "organizationId", "orgId", "tenantId", "workspaceId",
    "companyId", "accountId", "ownerId", "userId", "createdById",
    "createdByUserId", "authorId", "landlordId", "ORGANISATIONID", "OwnerId",
])
def test_runtime_filled_inputs_are_not_refused(name):
    doc = _wf(name)
    form = _bare_form()
    layout = {"root": {"type": "Stack", "children": [form]}}
    assert fc.unsatisfied_inputs(doc, {"id": "P", "route": "/x/new"},
                                 layout, form, "FLOW-001") == []


def test_ownership_rule_column_is_treated_as_runtime_supplied():
    doc = _wf("scopeCol")
    doc["security"] = {"ownershipRules": [{"entity": "E", "column": "scopeCol", "kind": "scope"}]}
    form = _bare_form()
    layout = {"root": {"type": "Stack", "children": [form]}}
    assert fc.unsatisfied_inputs(doc, {"id": "P"}, layout, form, "FLOW-001") == []


@pytest.mark.parametrize("name", ["vesselName", "vesselId", "petName", "title", "amount"])
def test_genuine_domain_fields_are_still_required(name):
    """The fix must not over-skip: a real user field with no Form to collect it
    is still refused, so a genuinely broken page is still caught."""
    doc = _wf(name)
    form = _bare_form()   # no fields
    layout = {"root": {"type": "Stack", "children": [form]}}
    missing = fc.unsatisfied_inputs(doc, {"id": "P"}, layout, form, "FLOW-001")
    assert missing and name in missing[0]


def test_a_form_that_collects_the_real_field_composes_even_with_an_ambient_one():
    """The MaritimeTalent case: a Form collects the user field (vesselName) but
    not the ambient organisationId. Before, organisationId refused the whole
    page; now it composes."""
    doc = {"workflows": [{"id": "FLOW-001", "name": "Create Vessel Profile", "inputs": [
        {"name": "organisationId", "kind": "field", "required": True},
        {"name": "vesselName", "kind": "field", "required": True}]}], "data": {"entities": []}}
    form = _bare_form("Submit Crew Request", fields=[{"name": "vesselName", "label": "Vessel name"}])
    layout = {"root": {"type": "Stack", "children": [form]}}
    assert fc.unsatisfied_inputs(doc, {"id": "P", "route": "/crew-request/new"},
                                 layout, form, "FLOW-001") == []


def test_a_non_required_input_is_never_checked():
    doc = _wf("vesselName", required=False)
    form = _bare_form()
    layout = {"root": {"type": "Stack", "children": [form]}}
    assert fc.unsatisfied_inputs(doc, {"id": "P"}, layout, form, "FLOW-001") == []


# ---------------------------------------------------------------------------
# Fix B — a page nothing composed gets a valid, marked fallback
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
           # only PAGE-002 composed
           "pageLayouts": [{"page": "PAGE-002",
                            "root": {"type": "Stack", "props": {}, "children": []}}]}
    res = plan_pages(doc, _CATALOG)
    assert set(res["planned"]) == {"PAGE-001", "PAGE-002", "PAGE-003"}
    assert res["planned"]["PAGE-002"]["meta"].get("fallback") in (None, False)
    assert res["planned"]["PAGE-001"]["meta"]["fallback"] is True
    assert res["planned"]["PAGE-003"]["meta"]["fallback"] is True
    assert set(res["fellBack"]) == {"PAGE-001", "PAGE-003"}
    # still reported, not silent
    assert {s["page"] for s in res["skipped"]} == {"PAGE-001", "PAGE-003"}


def test_a_broken_template_is_reported_not_masked_by_a_fallback():
    """A template that FAILS to plan (a real authoring error, e.g. requires an
    entity the page lacks) is reported in `failed` and left WITHOUT a schema —
    §76 keeps a genuine bug visible. The fallback is only for a page nothing
    composed, not for a broken composition."""
    # a pattern that requires a primary entity, but the page declares none
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
