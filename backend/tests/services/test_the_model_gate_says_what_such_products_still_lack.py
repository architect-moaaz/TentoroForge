"""At the reviews the person sees what such products have beside the
requirements, hears what the model does not answer yet, and can decline an
item or change the reference in a sentence; an agent may decline one too,
with a reason, through a change request."""
from __future__ import annotations

from services.blueprint.agent_contract import AgentResult, ChangeRequest, apply_agent_result, record_declines
from services.blueprint.service import BlueprintService
from services.smith import gates

REF = {"domain": "Retail", "subdomain": "Multi-vendor marketplace", "summary": "Shops sell through one storefront.",
       "screens": [{"name": "Order book", "purpose": "every order", "forRoles": ["Vendor"]},
                   {"name": "Dispute centre", "purpose": "disagreements"}],
       "records": [], "processes": [], "rules": [], "integrations": [], "conventions": ["SKU"], "benchmarks": []}


def _svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    s.doc["domainReference"] = dict(REF)
    s.doc["requirements"] = [{"id": "REQ-001", "description": "A vendor sees their orders.", "area": "Orders"}]
    s.doc["modules"] = [{"id": "MODULE-001", "name": "Orders", "description": "orders"}]
    s.doc["pages"] = [{"id": "PAGE-001", "name": "Orders", "route": "/orders", "purpose": "orders",
                       "module": "MODULE-001", "reference": "Order book", "requirements": ["REQ-001"]}]
    s.save()
    return s


def test_the_review_payload_carries_the_reference_and_its_coverage(tmp_path):
    svc = _svc(tmp_path)
    out = gates.payload(svc.doc, tmp_path)
    ref = out["reference"]
    assert ref["subdomain"] == "Multi-vendor marketplace" and [s["name"] for s in ref["screens"]] == ["Order book", "Dispute centre"]
    assert ref["coverage"]["total"] == 2 and ref["coverage"]["green"] == 1
    assert [r["item"] for r in ref["coverage"]["red"]] == ["Dispute centre"]


def test_the_model_is_said_with_what_such_products_still_lack(tmp_path):
    svc = _svc(tmp_path)
    said = gates.say_model(svc.doc)
    assert "1 thing such products have is not in the model yet: Dispute centre (screen)" in said
    assert "tell me to leave it out" in said
    svc.doc["domainReference"]["declined"] = [{"kind": "screen", "name": "Dispute centre", "reason": "v2", "by": "owner"}]
    assert "such products have" not in gates.say_model(svc.doc)


def test_the_person_can_decline_an_item_at_either_review(tmp_path):
    svc = _svc(tmp_path)
    out = gates.revise_requirements(svc, "", request="no dispute centre, we do that by email",
                                    decline=[{"kind": "screen", "name": "Dispute centre", "reason": "by email"}])
    assert out["declined"] == ["Dispute centre"]
    assert svc.doc["domainReference"]["declined"][0]["by"] == "owner"
    assert "left out of what such products have: Dispute centre" in \
        gates.say_requirements_change(out["diff"], out["version"], declined=out["declined"])
    assert "decline" in gates.TURN_SCHEMA["properties"] and "decline" in gates.TURN_SCHEMA["required"]
    assert "reference" in gates.PART_NODE and gates.PART_NODE["reference"] == "domain_reference"
    assert gates._PART_SECTIONS["reference"] == ("domainReference",)


def test_an_agent_declines_through_a_change_request_and_the_decline_is_recorded(tmp_path):
    svc = _svc(tmp_path)
    result = AgentResult(task_id="TASK-page_contracts-1", agent="page_design",
                         change_requests=[ChangeRequest(section="domainReference", reason="disputes go by email in v1",
                                                        proposed={"declined": [{"kind": "screen", "name": "Dispute centre"}]})])
    added = record_declines(svc, result)
    assert added == [{"kind": "screen", "name": "Dispute centre", "reason": "disputes go by email in v1", "by": "page_design"}]
    assert BlueprintService.load(output_dir=tmp_path).doc["domainReference"]["declined"] == added
    # Through the front door too: an empty result with the request applies and records.
    svc2 = _svc(tmp_path / "two")
    apply_agent_result(svc2, result)
    assert svc2.doc["domainReference"]["declined"][0]["name"] == "Dispute centre"
    # A request to another section is not a decline.
    svc3 = _svc(tmp_path / "three")
    other = AgentResult(task_id="TASK-x-1", agent="page_design",
                        change_requests=[ChangeRequest(section="workflows", reason="needs a flow", proposed={"declined": [{"kind": "screen", "name": "Dispute centre", "reason": "x"}]})])
    assert record_declines(svc3, other) == [] and not svc3.doc["domainReference"].get("declined")
