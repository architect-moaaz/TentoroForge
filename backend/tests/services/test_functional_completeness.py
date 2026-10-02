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


# ---------------------------------------------------------------------------
# The verb/op check is not delete-only: an Edit wired to Create, a Create wired
# to Update — any CRUD control that runs a workflow doing something other than
# what it says is caught (when a correctly-typed workflow exists to name).
# ---------------------------------------------------------------------------

def _crud_binding_doc(button_label: str, bound_wf: str):
    def _wf(wid, name, op):
        return {"id": wid, "name": name,
                "steps": [{"key": "s", "type": "action", "entity": "E",
                           "config": {"actionType": op, "table": "records"}}],
                "inputs": [{"name": "record", "kind": "record", "entity": "E", "required": True}]}
    layout = {"page": "PG", "dataSources": [{"name": "rec", "entity": "E", "op": "get"}],
              "root": {"type": "Stack", "props": {}, "children": [
                  {"type": "Button", "props": {"label": button_label, "workflow": bound_wf,
                                               "args": {"id": "{{rec.id}}"}}, "children": []}]}}
    return {
        "pages": [{"id": "PG", "route": "/records/[id]", "data": {"primaryEntity": "E"}}],
        "data": {"entities": [{"id": "E", "name": "Record", "table": "records",
                               "fields": [{"name": "fullName"}, {"name": "age"}]}]},
        "workflows": [_wf("FLOW-C", "Create Record", "db_insert"),
                      _wf("FLOW-U", "Update Record", "db_update"),
                      _wf("FLOW-D", "Delete Record", "db_delete")],
        "pageLayouts": [layout],
    }


def test_an_edit_button_wired_to_the_create_workflow_is_caught():
    doc = _crud_binding_doc("Edit Record", "FLOW-C")
    hits = [f for f in functional_findings(doc) if f["rule"] == "workflow-verb-mismatch"]
    assert hits and "Update Record" in hits[0]["detail"]  # names the correct target


def test_a_create_button_wired_to_the_update_workflow_is_caught():
    doc = _crud_binding_doc("Add Record", "FLOW-U")
    hits = [f for f in functional_findings(doc) if f["rule"] == "workflow-verb-mismatch"]
    assert hits and "Create Record" in hits[0]["detail"]


def test_a_correctly_wired_crud_control_is_accepted():
    doc = _crud_binding_doc("Edit Record", "FLOW-U")   # Edit -> Update, correct
    assert not [f for f in functional_findings(doc) if f["rule"] == "workflow-verb-mismatch"]


# ---------------------------------------------------------------------------
# A field change that leaves a workflow naming a column that is gone is caught —
# the dependency a rename/removal must not silently break.
# ---------------------------------------------------------------------------

def _write_doc(values_keys, where_keys=None):
    cfg = {"actionType": "db_update", "table": "records",
           "values": {k: "x" for k in values_keys}}
    if where_keys:
        cfg["where"] = {k: "x" for k in where_keys}
    return {
        "data": {"entities": [{"id": "E", "name": "Record", "table": "records",
                               "fields": [{"name": "fullName"}, {"name": "age"}]}]},
        "workflows": [{"id": "W", "name": "Update Record",
                       "steps": [{"key": "u", "config": cfg}]}],
        "businessRules": [], "pages": [], "pageLayouts": [],
    }


def test_a_workflow_naming_a_removed_column_is_caught():
    doc = _write_doc(["fullName", "gender"])   # gender was removed from the entity
    hits = [f for f in functional_findings(doc) if f["rule"] == "workflow-column-unknown"]
    assert hits and "gender" in hits[0]["detail"]


def test_system_columns_and_real_fields_are_not_flagged():
    doc = _write_doc(["fullName", "age", "updatedAt"], where_keys=["id"])
    assert not [f for f in functional_findings(doc) if f["rule"] == "workflow-column-unknown"]


# ---------------------------------------------------------------------------
# The form side of the field-dependency ripple: a Form collects fields the
# entity it writes still has. A field renamed/removed leaves the form collecting
# a value that goes nowhere. Mirror of unsatisfied_inputs.
# ---------------------------------------------------------------------------

def _form_doc(field_names):
    inputs = [{"type": "Input", "props": {"name": n}} for n in field_names]
    return {
        "pages": [{"id": "PG", "route": "/records/new", "data": {"primaryEntity": "E"}}],
        "data": {"entities": [{"id": "E", "name": "Record", "table": "records",
                               "fields": [{"name": "fullName"}, {"name": "age"}]}]},
        "workflows": [{"id": "FLOW-C", "name": "Create Record",
                       "inputs": [{"name": "fullName", "kind": "field"},
                                  {"name": "age", "kind": "field"}],
                       "steps": [{"key": "c", "config": {"actionType": "db_insert",
                                                          "table": "records"}}]}],
        "pageLayouts": [{"page": "PG",
                         "root": {"type": "Form", "props": {"workflow": "FLOW-C"},
                                  "children": [{"type": "Stack", "props": {}, "children": inputs}]}}],
    }


def test_a_form_field_that_is_no_longer_a_column_is_caught():
    doc = _form_doc(["fullName", "age", "nickname"])   # nickname removed from entity
    hits = [f for f in functional_findings(doc) if f["rule"] == "form-field-unknown"]
    assert hits and "nickname" in hits[0]["detail"]


def test_a_form_collecting_only_real_columns_is_accepted():
    doc = _form_doc(["fullName", "age"])
    assert not [f for f in functional_findings(doc) if f["rule"] == "form-field-unknown"]


def test_a_form_field_matching_a_workflow_input_is_accepted():
    # a field that is a declared input of the workflow (even if the column check
    # spelled it differently) is not orphaned.
    doc = _form_doc(["fullName", "age"])
    doc["workflows"][0]["inputs"].append({"name": "note", "kind": "field"})
    doc["pageLayouts"][0]["root"]["children"][0]["children"].append(
        {"type": "Input", "props": {"name": "note"}})
    assert not [f for f in functional_findings(doc) if f["rule"] == "form-field-unknown"]


def test_search_without_columns_is_advisory_not_a_composition_blocker():
    """The trap: an entity with no text column can't get one from the page
    composer, so refusing /members' search box just loops. The finding is still
    surfaced, but ADVISORY_PAGE_RULES keeps it out of the block set the composer
    is re-asked over (agent_contract.check_pattern_templates uses the same
    predicate)."""
    from services.blueprint.functional_completeness import (
        page_findings, ADVISORY_PAGE_RULES,
    )
    doc = {
        "pages": [{"id": "P", "route": "/lookups", "data": {"primaryEntity": "E"}}],
        "workflows": [],
        "data": {"entities": [{"id": "E", "name": "Lookup", "table": "lookups", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "count", "type": "integer"}]}]},
        "pageLayouts": [{"page": "P",
                         "dataSources": [{"name": "lk", "entity": "Lookup", "op": "list"}],
                         "root": {"type": "Stack", "children": [
                             {"type": "Input", "props": {"type": "search"}}]}}],
    }
    findings = page_findings(doc)
    assert "search-without-columns" in {f["rule"] for f in findings}   # still surfaced
    blocking = [f for f in findings if f["rule"] not in ADVISORY_PAGE_RULES]
    assert not any(f["rule"] == "search-without-columns" for f in blocking)  # not a blocker


# ---------------------------------------------------------------------------
# A page that declares an action must compose a control for it. The inverse of
# control-without-action: a re-compose of /master-data that DROPPED the Delete
# and Edit row actions passed every per-control check (no controls, nothing to
# check) and was accepted — "Delete does nothing" became "Delete is gone".
# ---------------------------------------------------------------------------

def _list_page_doc(row_actions=None, *, table_props=None, actions=("view", "edit", "delete", "create")):
    workflows = [
        {"id": "FLOW-001", "name": "Create Record",
         "steps": [{"key": "i", "type": "action", "entity": "E-REC",
                    "config": {"actionType": "db_insert", "table": "records"}}],
         "inputs": [{"name": "fullName", "kind": "field", "required": True}]},
        {"id": "FLOW-002", "name": "Update Record",
         "steps": [{"key": "u", "type": "action", "entity": "E-REC",
                    "config": {"actionType": "db_update", "table": "records"}}],
         "inputs": [{"name": "record", "kind": "record", "entity": "E-REC", "required": True}]},
        {"id": "FLOW-003", "name": "Delete Record",
         "steps": [{"key": "d", "type": "action", "entity": "E-REC",
                    "config": {"actionType": "db_delete", "table": "records"}}],
         "inputs": [{"name": "record", "kind": "record", "entity": "E-REC", "required": True}]},
    ]
    props = {"data": "{{records}}", "columns": [{"key": "fullName", "label": "Name"}]}
    if row_actions is not None:
        props["rowActions"] = row_actions
    props.update(table_props or {})
    return {
        "pages": [
            {"id": "PAGE-LIST", "route": "/master-data", "actions": list(actions),
             "data": {"primaryEntity": "E-REC"}},
            {"id": "PAGE-DET", "route": "/master-data/[id]", "actions": ["view"],
             "data": {"primaryEntity": "E-REC"}},
            {"id": "PAGE-ADD", "route": "/add-data", "actions": ["create"],
             "data": {"primaryEntity": "E-REC"}},
        ],
        "data": {"entities": [{"id": "E-REC", "name": "Record", "table": "records",
                               "fields": [{"name": "fullName", "type": "string"}]}]},
        "workflows": workflows,
        "pageLayouts": [
            {"page": "PAGE-LIST",
             "dataSources": [{"name": "records", "entity": "E-REC", "op": "list"}],
             "root": {"type": "Stack", "props": {}, "children": [
                 {"type": "Button", "props": {"label": "Add Record", "navigate": "/add-data"}, "children": []},
                 {"type": "Table", "props": props, "children": []},
             ]}},
            {"page": "PAGE-DET",
             "dataSources": [{"name": "rec", "entity": "E-REC", "op": "get"}],
             "root": {"type": "Text", "props": {"content": "{{rec.fullName}}"}, "children": []}},
            {"page": "PAGE-ADD",
             "dataSources": [],
             "root": {"type": "Form", "props": {"submitLabel": "Create Record", "workflow": "FLOW-001",
                                                "fields": [{"name": "fullName"}]}, "children": []}},
        ],
    }


_FULL_ROW_ACTIONS = [
    {"label": "View", "navigate": "/master-data/{{id}}"},
    {"label": "Edit", "navigate": "/add-data?id={{id}}"},
    {"label": "Delete", "workflow": "FLOW-003", "variant": "danger"},
]


def _declared(doc, page="PAGE-LIST"):
    return [f["detail"] for f in functional_findings(doc)
            if f["rule"] == "declared-action-without-control" and f["page"] == page]


def test_a_list_page_with_every_declared_control_is_accepted():
    doc = _list_page_doc(_FULL_ROW_ACTIONS)
    assert [f for f in functional_findings(doc) if f["page"] == "PAGE-LIST"] == []


def test_dropping_the_delete_and_edit_row_actions_is_refused():
    """Attempt 18 on DC5: the composer answered a column complaint by
    re-composing the table without its row actions. Accepted then; refused now,
    with the control and its workflow named."""
    doc = _list_page_doc([])                  # table kept, actions gone
    details = _declared(doc)
    assert len(details) == 3                  # view, edit, delete — in the page's own order
    assert "declares `view`" in details[0] and "/master-data/[id]" in details[0]
    assert "declares `edit`" in details[1] and "Update Record (FLOW-002)" in details[1]
    assert "declares `delete`" in details[2] and "Delete Record (FLOW-003)" in details[2]
    assert "rowActions" in details[2]


def test_view_is_satisfied_by_a_row_click_or_a_link_to_the_record_page():
    only_delete = [{"label": "Delete", "workflow": "FLOW-003"}, {"label": "Edit", "navigate": "/add-data?id={{id}}"}]
    doc = _list_page_doc(only_delete)
    assert [d for d in _declared(doc) if "`view`" in d]
    doc = _list_page_doc(only_delete, table_props={"onRowClick": {"navigate": "/master-data/{{id}}"}})
    assert _declared(doc) == []
    doc = _list_page_doc(only_delete + [{"label": "Open", "navigate": "/master-data/{id}"}])
    assert _declared(doc) == []


def test_a_create_form_page_is_not_asked_to_update_what_it_cannot_name():
    """/add-data declares `update` as well (the contract imagines one form that
    creates or edits). A Form runs one workflow and nothing on that route names
    a record, so a control there would be refused for its inputs; the
    declaration is the planner's to reshape, not a hole the composer left."""
    doc = _list_page_doc(_FULL_ROW_ACTIONS)
    doc["pages"][2]["actions"] = ["create", "update"]
    assert _declared(doc, "PAGE-ADD") == []
    # The same declaration on the record's own page IS the composer's: the
    # route names the record and nothing updates or deletes it.
    doc["pages"][1]["actions"] = ["view", "edit", "delete"]
    details = _declared(doc, "PAGE-DET")
    assert [d.split(" on ")[0] for d in details] == [
        "/master-data/[id] declares `edit`", "/master-data/[id] declares `delete`"]


def test_a_form_page_satisfies_create_with_its_own_form():
    doc = _list_page_doc(_FULL_ROW_ACTIONS)
    assert _declared(doc, "PAGE-ADD") == []
    doc["pageLayouts"][2]["root"] = {"type": "Text", "props": {"content": "nothing here"}, "children": []}
    (d,) = _declared(doc, "PAGE-ADD")
    assert "declares `create`" in d and "Create Record (FLOW-001)" in d


def test_the_record_page_itself_is_not_asked_for_a_view_control():
    doc = _list_page_doc(_FULL_ROW_ACTIONS)
    assert _declared(doc, "PAGE-DET") == []


def test_nothing_to_bind_is_not_the_composers_finding():
    # No delete workflow at all: the gap is Page↔Workflow's (the review declares
    # it); asking the composer for a control it cannot bind would only burn rounds.
    doc = _list_page_doc([{"label": "Edit", "navigate": "/add-data?id={{id}}"},
                          {"label": "View", "navigate": "/master-data/{{id}}"}])
    doc["workflows"] = [w for w in doc["workflows"] if w["id"] != "FLOW-003"]
    assert _declared(doc) == []


def test_a_bound_flow_id_action_and_unknown_verbs_are_left_alone():
    doc = _list_page_doc(_FULL_ROW_ACTIONS, actions=("FLOW-003", "export", "filter_by_gender"))
    assert _declared(doc) == []


def test_the_missing_control_is_a_refusal_not_advice():
    from services.blueprint.functional_completeness import ADVISORY_PAGE_RULES
    assert "declared-action-without-control" not in ADVISORY_PAGE_RULES


def test_an_edit_is_demanded_only_where_there_is_a_page_to_edit_on():
    """A row action cannot run Update itself (a table collects no fields); an
    Edit on a list is a navigation to the form or record page. With neither,
    the verb has nowhere to go and the composer is not asked for it."""
    doc = _list_page_doc([{"label": "Delete", "workflow": "FLOW-003"},
                          {"label": "View", "navigate": "/master-data/{{id}}"}])
    assert [d for d in _declared(doc) if "`edit`" in d]                 # /add-data exists → demanded
    doc["pages"] = [p for p in doc["pages"] if p["id"] == "PAGE-LIST"]
    doc["pageLayouts"] = [l for l in doc["pageLayouts"] if l["page"] == "PAGE-LIST"]
    assert [d for d in _declared(doc) if "`edit`" in d] == []           # nowhere to edit → silent


def test_a_create_is_demanded_only_where_there_is_a_form_to_go_to():
    doc = _list_page_doc(_FULL_ROW_ACTIONS)
    doc["pageLayouts"][0]["root"]["children"].pop(0)                          # drop "Add Record"
    assert [d for d in _declared(doc) if "`create`" in d]                     # /add-data exists → demanded
    doc["pages"] = [p for p in doc["pages"] if p["id"] != "PAGE-ADD"]
    doc["pageLayouts"] = [l for l in doc["pageLayouts"] if l["page"] != "PAGE-ADD"]
    assert [d for d in _declared(doc) if "`create`" in d] == []               # nowhere to create → silent


def test_a_view_of_something_that_is_not_the_record_asks_for_no_link():
    """h7gmi93x's /add-data declared `view inline validation errors`; read as
    "view a Record" it demanded a link to /master-data/[id] and refused the
    create form's every template. Viewing ERRORS opens no record."""
    doc = _list_page_doc([{"label": "Delete", "workflow": "FLOW-003"},
                          {"label": "Edit", "navigate": "/add-data?id={{id}}"}],
                         actions=("view inline validation errors", "see success confirmation"))
    assert _declared(doc) == []
    # The record, however it is called, is still demanded.
    for label in ("view", "view details", "open record"):
        doc = _list_page_doc([{"label": "Delete", "workflow": "FLOW-003"}], actions=(label,))
        assert [d for d in _declared(doc) if f"`{label}`" in d], label


def test_a_page_written_as_code_is_not_reported_as_uncomposed():
    """A pageCode row IS the page: its route files render it. The finding
    `/add-data has no composed tree` was printed under a build whose /add-data
    rendered from its own view.tsx."""
    from services.blueprint.functional_completeness import page_findings
    doc = _list_page_doc(_FULL_ROW_ACTIONS)
    doc["pageLayouts"] = [l for l in doc["pageLayouts"] if l["page"] != "PAGE-ADD"]
    assert [f for f in page_findings(doc) if f["rule"] == "page-not-composed"]
    doc["pageCode"] = [{"page": "PAGE-ADD", "rationale": "", "load": "", "view": "export default function View() {}"}]
    assert [f for f in page_findings(doc) if f["rule"] == "page-not-composed"] == []
