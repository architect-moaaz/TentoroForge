"""§73 — would the application described actually work?"""

from services.blueprint.functional_completeness import (
    functional_findings,
    unsatisfied_inputs,
)


def _flow_doc(ownership):
    """A create flow needing a session-filled field (organisationId) and a
    genuine user field (name); `ownership` seeds security.ownershipRules."""
    return {
        "pages": [{"id": "PAGE-001", "route": "/vessels/new"}],
        "data": {"entities": []},
        "security": {"ownershipRules": ownership},
        "workflows": [{"id": "FLOW-001", "name": "Create Vessel", "inputs": [
            {"name": "organisationId", "kind": "field", "type": "uuid", "required": True},
            {"name": "name", "kind": "field", "type": "text", "required": True},
        ]}],
    }


def test_a_session_filled_field_is_not_demanded_of_a_form():
    # organisationId is an ownership `scope` column — the runtime fills it from
    # the session, so a create form need not (and must not) collect it, while a
    # genuine user field like `name` is still required. Driven by the declared
    # ownershipRules manifest, not a hardcoded field-name list.
    doc = _flow_doc([{"column": "organisationId", "entity": "Vessel", "kind": "scope"}])
    control = {"type": "Button", "props": {"label": "Create", "workflow": "FLOW-001"}}
    layout = {"root": {"type": "Stack", "props": {}, "children": [control]}}
    msgs = " ".join(unsatisfied_inputs(doc, doc["pages"][0], layout, control, "FLOW-001"))
    assert "organisationId" not in msgs
    assert "'name'" in msgs


def test_without_the_ownership_rule_the_field_is_demanded():
    # No provenance declared -> organisationId is an ordinary input the form
    # must collect, so the check still flags it. Proves the exemption is the
    # manifest's doing, not a special-cased name.
    doc = _flow_doc([])
    control = {"type": "Button", "props": {"label": "Create", "workflow": "FLOW-001"}}
    layout = {"root": {"type": "Stack", "props": {}, "children": [control]}}
    msgs = " ".join(unsatisfied_inputs(doc, doc["pages"][0], layout, control, "FLOW-001"))
    assert "organisationId" in msgs


def _route_id_doc(with_detail=True):
    """An action sub-page (`/tools/[id]/request`) that CREATES a Rental but whose
    `[id]` names the ToolListing being requested; the id-bearing prefix
    `/tools/[id]` is the ToolListing detail page that declares what the id is."""
    pages = [{"id": "PAGE-REQ", "route": "/tools/[id]/request",
              "data": {"primaryEntity": "ENTITY-RENTAL"}}]
    if with_detail:
        pages.append({"id": "PAGE-TOOL", "route": "/tools/[id]",
                      "data": {"primaryEntity": "ENTITY-TOOL"}})
    return {
        "pages": pages,
        "data": {"entities": [{"id": "ENTITY-TOOL", "name": "ToolListing"},
                              {"id": "ENTITY-RENTAL", "name": "Rental"}]},
        "workflows": [{"id": "FLOW-REQ", "name": "Request Rental", "inputs": [
            {"name": "toolListing", "kind": "record", "entity": "ENTITY-TOOL", "required": True},
        ]}],
    }


def test_a_record_named_by_the_routes_own_id_segment_is_in_scope():
    # The page's primaryEntity is the Rental it creates, so the ToolListing the
    # workflow consumes is invisible to a primaryEntity-only check — but the
    # route's own `[id]` (via the `/tools/[id]` detail page) names it.
    doc = _route_id_doc(with_detail=True)
    control = {"type": "Form", "props": {"submitLabel": "Send Request", "workflow": "FLOW-REQ"}}
    layout = {"root": {"type": "Stack", "props": {}, "children": [control]}}
    msgs = " ".join(unsatisfied_inputs(doc, doc["pages"][0], layout, control, "FLOW-REQ"))
    assert msgs == ""


def test_without_the_detail_page_the_routes_id_names_nothing():
    # No `/tools/[id]` page exists, so the route's id resolves to no entity and
    # the ToolListing is genuinely unnamed — still flagged. Proves the scope
    # comes from the sibling detail page's evidence, not from parsing the URL.
    doc = _route_id_doc(with_detail=False)
    control = {"type": "Form", "props": {"submitLabel": "Send Request", "workflow": "FLOW-REQ"}}
    layout = {"root": {"type": "Stack", "props": {}, "children": [control]}}
    msgs = " ".join(unsatisfied_inputs(doc, doc["pages"][0], layout, control, "FLOW-REQ"))
    assert "ToolListing" in msgs and "toolListing" in msgs


def _kyc_doc(with_rule=True):
    """A self-service intake (`/kyc-verifications/new`) whose workflow needs a
    `member` record — the signed-in person, stamped by the runtime from the
    session via the KycVerification's `memberId` scope column."""
    rules = ([{"column": "memberId", "entity": "KycVerification",
               "kind": "scope", "scope": "user"}] if with_rule else [])
    return {
        "pages": [{"id": "PAGE-KYC", "route": "/kyc-verifications/new",
                   "data": {"primaryEntity": "ENTITY-KYC"}}],
        "data": {"entities": [{"id": "ENTITY-MEMBER", "name": "Member"},
                              {"id": "ENTITY-KYC", "name": "KycVerification"}]},
        "security": {"ownershipRules": rules},
        "workflows": [{"id": "FLOW-KYC", "name": "Submit KYC Verification", "inputs": [
            {"name": "member", "kind": "record", "entity": "ENTITY-MEMBER", "required": True},
            {"name": "documentNumber", "kind": "field", "type": "text", "required": True},
        ]}],
    }


def test_the_acting_users_own_record_is_session_filled():
    # `member` is the signed-in person filling in their own KYC, supplied from
    # the session via the primary entity's `memberId` scope column — a Form must
    # not name it. A genuine field like `documentNumber` is still demanded.
    doc = _kyc_doc(with_rule=True)
    control = {"type": "Form", "props": {"submitLabel": "Submit", "workflow": "FLOW-KYC"}}
    layout = {"root": {"type": "Stack", "props": {}, "children": [control]}}
    msgs = " ".join(unsatisfied_inputs(doc, doc["pages"][0], layout, control, "FLOW-KYC"))
    assert "Member record" not in msgs
    assert "documentNumber" in msgs


def test_without_the_scope_rule_the_record_is_demanded():
    # No ownership rule ties the member to the session, and the route names no
    # Member -> the record is genuinely unnamed and still flagged. Proves the
    # exemption is the manifest's doing, not a special-cased entity name.
    doc = _kyc_doc(with_rule=False)
    control = {"type": "Form", "props": {"submitLabel": "Submit", "workflow": "FLOW-KYC"}}
    layout = {"root": {"type": "Stack", "props": {}, "children": [control]}}
    msgs = " ".join(unsatisfied_inputs(doc, doc["pages"][0], layout, control, "FLOW-KYC"))
    assert "Member record" in msgs


def _doc(root, sources=None, workflows=("FLOW-001",)):
    return {
        "pages": [{"id": "PAGE-001", "route": "/plants"}],
        "workflows": [{"id": w, "name": w} for w in workflows],
        "pageLayouts": [{"page": "PAGE-001", "root": root,
                         "dataSources": [{"name": n} for n in (sources or [])]}],
    }


def _rules(doc):
    return sorted(f["rule"] for f in functional_findings(doc))


def test_a_control_with_no_action_is_a_defect():
    """Five buttons on one generated page carried a label and nothing else.
    They render, they are clickable, and nothing happens — indistinguishable
    from a broken application, with no error to diagnose from."""
    doc = _doc({"type": "Button", "props": {"label": "Mark Watered Today"}})
    assert _rules(doc) == ["control-without-action"]
    assert "would do nothing" in functional_findings(doc)[0]["detail"]


def test_a_control_that_acts_is_fine():
    for prop, value in (("workflow", "FLOW-001"), ("navigate", "/x"),
                        ("submit", True), ("opensDialog", "d")):
        button = {"type": "Button", "props": {"label": "Go", prop: value}}
        # A dialog target must exist on the page — five real buttons opened
        # dialogs by id that no node carried, and did nothing.
        node = ({"type": "Stack", "props": {}, "children": [
                    button, {"id": "d", "type": "Dialog", "props": {"title": "Go"}, "children": []}]}
                if prop == "opensDialog" else button)
        doc = _doc(node)
        assert _rules(doc) == [], prop


def test_a_workflow_that_does_not_exist_is_caught_at_any_depth():
    """`Table.rowActions[0].workflow` is where an invented id shipped; a check
    that reads one key walks past it."""
    doc = _doc({"type": "Table", "props": {
        "rows": "{{plants}}",
        "rowActions": [{"label": "Mark", "workflow": "markPlantWatered"}]}},
        sources=["plants"])
    assert _rules(doc) == ["workflow-not-defined"]


def test_a_binding_with_no_source_is_caught():
    """`{{overdue.value}}` with no `overdue` source renders the template text
    itself to whoever opens the page."""
    doc = _doc({"type": "Stat", "props": {"value": "{{overdue.value}}"}})
    assert _rules(doc) == ["binding-without-source"]


def test_a_bound_source_is_fine():
    doc = _doc({"type": "Table", "props": {"rows": "{{plants}}"}},
               sources=["plants"])
    assert _rules(doc) == []


def test_a_page_nothing_composed_is_caught():
    """The Blueprint still claims the page exists, and every consumer believes
    it — while the route 404s."""
    doc = _doc({"type": "Stack"})
    doc["pageLayouts"] = []
    assert _rules(doc) == ["page-not-composed"]


def test_findings_nest_through_children():
    doc = _doc({"type": "Stack", "children": [
        {"type": "Row", "children": [
            {"type": "Button", "props": {"label": "Deep"}}]}]})
    assert _rules(doc) == ["control-without-action"]


def test_the_action_list_comes_from_the_composer_contract():
    """Hand-listing them is how `opensDialog` came to be refused on a page
    whose create form was a modal — the list held four of the six offered."""
    from services.blueprint.functional_completeness import _action_props

    assert {"workflow", "navigate", "submit", "onClick",
            "opensDialog", "togglesSidebar"} <= _action_props()


# ---------------------------------------------------------------------------
# The findings are rejections, not a report.
# ---------------------------------------------------------------------------

def _proposal(root):
    from services.blueprint.executors import AgentResult, ArtifactProposal

    return AgentResult(
        task_id="t", agent="a2ui_pages", status="completed",
        proposals=[ArtifactProposal(
            section="pageLayouts", natural_key="PAGE-001",
            body={"page": "PAGE-001", "root": root})],
    )


def test_a_dead_control_is_refused_so_the_composer_is_asked_again():
    """§73 closes the loop: the orchestrator re-asks a node when its output is
    refused, so a button with no action is a page composed wrongly rather than
    a page to repair afterwards."""
    import pytest

    from services.blueprint.agent_contract import (
        InvalidPatternTemplate, check_pattern_templates,
    )

    result = _proposal({"type": "Stack", "props": {}, "children": [
        {"type": "Button", "props": {"label": "Cancel"}, "children": []}]})
    doc = {"pages": [{"id": "PAGE-001", "route": "/plants"}], "workflows": []}

    with pytest.raises(InvalidPatternTemplate) as exc:
        check_pattern_templates(result, doc)
    # The reason reaches the agent verbatim, so it can act on it.
    assert "declares no action" in str(exc.value)


def test_a_working_control_is_accepted():
    from services.blueprint.agent_contract import check_pattern_templates

    result = _proposal({"type": "Stack", "props": {}, "children": [
        {"type": "Button", "props": {"label": "Water", "workflow": "FLOW-001"},
         "children": []}]})
    check_pattern_templates(result, {
        "pages": [{"id": "PAGE-001", "route": "/plants"}],
        "workflows": [{"id": "FLOW-001", "name": "Record Watering"}]})


def test_without_a_doc_the_functional_check_is_skipped():
    """A caller that cannot say which workflows exist would otherwise reject
    every real binding as invented."""
    from services.blueprint.agent_contract import check_pattern_templates

    result = _proposal({"type": "Stack", "props": {}, "children": [
        {"type": "Button", "props": {"label": "Cancel"}, "children": []}]})
    check_pattern_templates(result)   # structure only — must not raise


# ---------------------------------------------------------------------------
# A DESTRUCTIVE CONTROL DELETES. A "Delete" button wired to an Update workflow
# changes the record instead of removing it — nothing a person can see happens,
# which reads as a broken button. `workflow-not-defined` never sees it: the
# Update workflow exists, so the reference resolves.
# ---------------------------------------------------------------------------

def _delete_binding_doc(*, delete_wf: bool):
    """A Record detail page whose Delete button is wired to the UPDATE workflow.
    `delete_wf` seeds whether a real Delete workflow (db_delete) also exists."""
    workflows = [
        {"id": "FLOW-UPD", "name": "Update Record",
         "steps": [{"key": "u", "type": "action", "entity": "E-REC",
                    "config": {"actionType": "db_update", "table": "records"}}],
         "inputs": [{"name": "record", "kind": "record", "entity": "E-REC", "required": True}]},
    ]
    if delete_wf:
        workflows.append(
            {"id": "FLOW-DEL", "name": "Delete Record",
             "steps": [{"key": "d", "type": "action", "entity": "E-REC",
                        "config": {"actionType": "db_delete", "table": "records"}}],
             "inputs": [{"name": "record", "kind": "record", "entity": "E-REC", "required": True}]})
    layout = {
        "page": "PAGE-DET",
        "dataSources": [{"name": "rec", "entity": "E-REC", "op": "get"}],
        "root": {"type": "Stack", "props": {}, "children": [
            {"type": "Button", "props": {
                "label": "Delete Record", "variant": "danger", "workflow": "FLOW-UPD",
                "args": {"id": "{{rec.id}}"}}, "children": []},
        ]},
    }
    return {
        "pages": [{"id": "PAGE-DET", "route": "/records/[id]",
                   "data": {"primaryEntity": "E-REC"}}],
        "data": {"entities": [{"id": "E-REC", "name": "Record", "table": "records"}]},
        "workflows": workflows,
        "pageLayouts": [layout],
    }


def test_a_delete_button_wired_to_update_is_refused_when_a_delete_workflow_exists():
    doc = _delete_binding_doc(delete_wf=True)
    rules = {f["rule"] for f in functional_findings(doc)}
    assert "workflow-verb-mismatch" in rules
    detail = next(f["detail"] for f in functional_findings(doc)
                  if f["rule"] == "workflow-verb-mismatch")
    # Names the correct target so the composer can rebind.
    assert "Delete Record" in detail


def test_a_delete_button_is_not_double_flagged_when_no_delete_workflow_exists():
    # With no Delete workflow to name, the mismatch is the workflow author's to
    # fix (Page↔Workflow), not the composer's — demanding a rebind here would
    # point at a target that does not exist. So page-side stays silent.
    doc = _delete_binding_doc(delete_wf=False)
    rules = {f["rule"] for f in functional_findings(doc)}
    assert "workflow-verb-mismatch" not in rules


def test_a_delete_button_wired_to_the_delete_workflow_is_accepted():
    doc = _delete_binding_doc(delete_wf=True)
    doc["pageLayouts"][0]["root"]["children"][0]["props"]["workflow"] = "FLOW-DEL"
    rules = {f["rule"] for f in functional_findings(doc)}
    assert "workflow-verb-mismatch" not in rules
