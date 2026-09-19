"""A page's contract says what it shows, and every fact has a source.

Tool Share's tool page was a list of tasks over a Tool with two columns; the
page printed an id. The content plan names each fact a reader weighs and where
it comes from, refuses a source the data model does not have, and grows the
data model — before workflows are written — when a page needs a field.
"""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidPageContent, check_page_content,
)
from services.blueprint.page_content import (
    content_brief, content_findings, entity_bodies_with_requested_fields, process_grounding,
    requested_fields,
)

TOOL, MEMBER, RENTAL, KYC = "ENTITY-003", "ENTITY-001", "ENTITY-004", "ENTITY-002"


def _doc(**over):
    doc = {
        "data": {"entities": [
            {"id": MEMBER, "name": "Member", "table": "members", "labelField": "fullName",
             "fields": [{"name": "id", "type": "uuid"}, {"name": "fullName", "type": "string"}]},
            {"id": KYC, "name": "KycVerification", "table": "kyc", "fields": [
                {"name": "id", "type": "uuid"}, {"name": "memberId", "type": "uuid", "references": MEMBER},
                {"name": "status", "type": "enum", "enumValues": ["pending", "approved"]}]},
            {"id": TOOL, "name": "Tool", "table": "tools", "fields": [
                {"name": "id", "type": "uuid"}, {"name": "name", "type": "string"},
                {"name": "ownerId", "type": "uuid", "references": MEMBER}]},
            {"id": RENTAL, "name": "Rental", "table": "rentals", "fields": [
                {"name": "id", "type": "uuid"}, {"name": "toolId", "type": "uuid", "references": TOOL},
                {"name": "status", "type": "string"}]},
        ]},
        "businessRules": [
            {"id": "RULE-001", "name": "Handover requires condition evidence",
             "statement": "A rental cannot become active until condition photos are recorded."},
            {"id": "RULE-002", "name": "Reviews are written only", "statement": "No star rating."},
        ],
        "workflows": [],
        "pages": [],
    }
    doc.update(over)
    return doc


def _page(*content, route="/tools/[id]"):
    return {"id": "PAGE-008", "route": route, "name": "Tool", "data": {"primaryEntity": TOOL},
            "content": list(content)}


def _item(label, **source):
    return {"label": label, "answers": f"about {label}", "source": source}


GOOD = [
    _item("Name", kind="field", field="name"),
    _item("What's included", kind="field", field="includedItems",
          newField={"type": "string[]", "description": "Accessories"}),
    _item("Owner", kind="related", via="ownerId", entity=MEMBER, field="fullName"),
    _item("Loans", kind="count", entity=RENTAL, via="toolId", where={"status": "completed"}),
    _item("Owner verified", kind="count", entity=KYC, via="memberId", of="ownerId",
          where={"status": "approved"}),
    _item("Condition-checked handover", kind="process", about="condition photos at handover"),
]


def test_a_plan_whose_sources_all_resolve_passes():
    assert content_findings(_page(*GOOD), _doc()) == []


@pytest.mark.parametrize("item, fault", [
    (_item("Category", kind="field", field="category"), "propose it in `source.newField`"),
    (_item("Category", kind="field", field="category", newField={"type": "colour"}), "is not one of"),
    (_item("Category", kind="field", field="category", newField={"type": "enum"}), "enumValues"),
    (_item("Owner", kind="related", via="nope", entity=MEMBER), "`via` must be a foreign key"),
    (_item("Owner", kind="related", via="ownerId", entity=RENTAL), "references ENTITY-001"),
    (_item("Loans", kind="count", entity=RENTAL, via="nope"), "`via` must be the field of Rental"),
    (_item("Loans", kind="count", entity=KYC, via="memberId"), "use `of`"),
    (_item("Loans", kind="count", entity=RENTAL, via="toolId", where={"colour": "x"}), "`where` names"),
    (_item("Total", kind="total", entity=RENTAL, via="toolId", fn="sum", field="nope"), "numeric `field`"),
    (_item("Loans", kind="count", entity="ENTITY-099", via="toolId"), "not in the data model"),
    (_item("Next", kind="process"), "`about`"),
])
def test_a_source_that_does_not_resolve_is_named(item, fault):
    findings = content_findings(_page(item), _doc())
    assert findings and fault in findings[0], findings


def test_the_author_is_refused_at_apply():
    result = AgentResult(task_id="T", agent="page_design", confidence=1.0, proposals=[
        ArtifactProposal(section="pages", natural_key="PAGE:/tools/[id]",
                         body=_page(_item("Loans", kind="count", entity=RENTAL, via="nope")))])
    with pytest.raises(InvalidPageContent, match="`via` must be"):
        check_page_content(result, _doc())
    ok = AgentResult(task_id="T", agent="page_design", confidence=1.0, proposals=[
        ArtifactProposal(section="pages", natural_key="PAGE:/tools/[id]", body=_page(*GOOD))])
    check_page_content(ok, _doc())


def test_a_needed_field_is_requested_once_and_not_when_present():
    doc = _doc(pages=[_page(*GOOD), _page(GOOD[1], route="/tools")])
    assert requested_fields(doc) == {TOOL: [{"name": "includedItems", "type": "string[]", "required": False,
                                              "sensitive": False, "description": "Accessories"}]}
    (body,) = entity_bodies_with_requested_fields(doc)
    assert [f["name"] for f in body["fields"]] == ["id", "name", "ownerId", "includedItems"]
    doc["data"]["entities"][2]["fields"].append({"name": "includedItems", "type": "string[]"})
    assert requested_fields(doc) == {}


def test_a_related_records_missing_field_is_requested_on_it():
    item = _item("Owner area", kind="related", via="ownerId", entity=MEMBER, field="area",
                 newField={"type": "string"})
    doc = _doc(pages=[_page(item)])
    assert content_findings(doc["pages"][0], doc) == []
    assert [f["name"] for f in requested_fields(doc)[MEMBER]] == ["area"]


def test_the_fields_are_added_to_the_data_model_before_workflows(tmp_path):
    from services.blueprint.orchestrator import DAG, SERVICE_HANDLERS
    from services.blueprint.service import BlueprintService

    assert DAG["content_fields"].kind == "service"
    assert DAG["content_fields"].depends_on == {"page_details"}
    for later in ("workflows", "apis", "analytics", "page_layouts"):
        assert "content_fields" in DAG[later].depends_on, later

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="T", domain="ops")
    svc.upsert("data.entities", {"name": "Tool", "table": "tools",
                                 "fields": [{"name": "id", "type": "uuid"}]}, natural_key="Tool")
    tool = svc.doc["data"]["entities"][0]["id"]
    svc.upsert("pages", {"name": "Tool", "route": "/tools/[id]", "purpose": "x",
                         "data": {"primaryEntity": tool},
                         "content": [_item("Category", kind="field", field="category",
                                           newField={"type": "enum", "enumValues": ["power", "hand"]})]},
               natural_key="PAGE:/tools/[id]")
    SERVICE_HANDLERS["content_fields"](svc)
    fields = {f["name"]: f for f in svc.doc["data"]["entities"][0]["fields"]}
    assert fields["category"]["enumValues"] == ["power", "hand"] and "id" in fields
    SERVICE_HANDLERS["content_fields"](svc)          # idempotent: nothing left to add
    assert [f["name"] for f in svc.doc["data"]["entities"][0]["fields"]].count("category") == 1


def test_the_engineer_gets_each_fact_with_its_read():
    doc = _doc(pages=[_page(*GOOD)])
    brief = {b["label"]: b for b in content_brief(doc, doc["pages"][0])}
    assert brief["Loans"]["read"] == "count(\"Rental\", { toolId: tool.id, status: 'completed' })"
    assert brief["Owner verified"]["read"] == \
        "count(\"KycVerification\", { memberId: tool.ownerId, status: 'approved' })"
    assert brief["Owner"]["read"] == '(await record("Member", tool.ownerId))?.fullName'
    listing = content_brief(doc, _page(GOOD[2], route="/tools"))[0]["read"]
    assert listing.startswith('recordsById("Member"')


def test_process_copy_is_grounded_in_the_rule_it_is_about():
    doc = _doc(pages=[_page(*GOOD)])
    grounding = process_grounding(doc, doc["pages"][0])
    assert grounding[0].startswith("rule — Handover requires condition evidence")
    assert process_grounding(doc, _page(GOOD[0])) == []


def test_the_brief_and_the_prompts_carry_the_plan():
    from services.blueprint.executors import NODE_TASKS
    from services.blueprint.ui_engineer import DESIGN_PRINCIPLES, _page_brief

    doc = _doc(pages=[_page(*GOOD)])
    brief = _page_brief(doc, doc["pages"][0])
    assert [c["label"] for c in brief["content"]][:2] == ["Name", "What's included"]
    assert brief["writeProcessCopyFrom"]
    assert "content" not in _page_brief(doc, _page())
    assert "THE CONTENT PLAN IS THE PAGE" in DESIGN_PRINCIPLES
    assert "SAY WHAT EACH PAGE SAYS" in NODE_TASKS["page_details"]
    assert "never invent a figure" in NODE_TASKS["page_details"]
    assert "LOOKS AT to decide" in NODE_TASKS["entity_fields"]


def test_the_last_attempt_keeps_what_resolves_and_the_contract():
    from services.blueprint.page_content import drop_unresolved_content

    bad = _item("Loans", kind="count", entity=RENTAL, via="nope")
    result = AgentResult(task_id="T", agent="page_design", confidence=1.0, proposals=[
        ArtifactProposal(section="pages", natural_key="PAGE:/tools/[id]", body=_page(GOOD[0], bad))])
    dropped = drop_unresolved_content(result, _doc())
    assert len(dropped) == 1 and "`via` must be" in dropped[0]
    assert [c["label"] for c in result.proposals[0].body["content"]] == ["Name"]
    check_page_content(result, _doc())          # now accepted
