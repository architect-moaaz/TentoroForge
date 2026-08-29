"""Verification's job is to notice, and then to stop.

Every check here has an ancestor in the old platform — a guard that found the
same defect and immediately patched it. `action_contract_guard` repaired button
args; `fk_source_guard` reconciled foreign keys; `navigate_target_guard`
rewrote broken hrefs or tagged them `data-nav-warn`. Each fix was individually
correct and collectively produced a 151-step chain nobody could reason about.

So the assertions that matter most are the negative ones: after verification
runs, the Blueprint's *content* is byte-identical. Only statuses move.
"""
import json

import pytest

from services.blueprint.agent_contract import capability_for
from services.blueprint.ids import entity_key, page_key, prose_key
from services.blueprint.service import BlueprintService
from services.blueprint.verification import (
    CHECKS,
    EDGES,
    SECTION_OWNER,
    apply_findings,
    requirement_verdict,
    verify,
)


def doc(**sections) -> dict:
    base = {
        "schemaVersion": "1",
        "version": 1,
        "state": "IMPLEMENTATION",
        "application": {"id": "a", "name": "Recruitment", "domain": "ATS"},
    }
    base.update(sections)
    return base


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    return BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="Recruitment", domain="ATS"
    )


# --- the matrix is declared, not implied ------------------------------------

def test_all_ten_section_75_edges_are_implemented():
    """The PRD's ten, plus the edges the migration ledger added."""
    from services.blueprint.migration_ledger import new_edges_required
    assert set(CHECKS) == set(EDGES)
    prd_ten = set(EDGES) - {"Navigation↔Page", "Page↔Workflow", "Widget↔DataSource",
                            "Page↔Layout"}
    assert len(prd_ten) == 10
    assert new_edges_required() <= set(EDGES)


def test_every_section_owner_may_actually_write_that_section():
    """Routing a repair task to an agent that cannot perform it would produce a
    task nobody can close (§74 + §30)."""
    for section, agent in SECTION_OWNER.items():
        cap = capability_for(agent)
        assert cap.can_write(section) or not cap.writes, (section, agent)


def test_a_coherent_blueprint_produces_no_findings():
    d = doc(
        roles=[{"id": "ROLE-001", "name": "recruiter"}],
        permissions=[{"id": "PERM-001", "name": "write candidates", "action": "create"}],
        data={"entities": [{"id": "ENTITY-001", "name": "Candidate", "table": "candidates"}]},
        apis=[{"id": "API-001", "method": "POST", "path": "/api/candidates",
               "entity": "ENTITY-001", "permission": "PERM-001"}],
        pages=[{"id": "PAGE-001", "name": "Candidates", "route": "/candidates",
                "purpose": "Manage candidates.", "users": ["ROLE-001"],
                "actions": ["create"], "data": {"primaryEntity": "ENTITY-001"},
                "requirements": ["REQ-001"], "status": "IMPLEMENTED"}],
        requirements=[{"id": "REQ-001", "description": "Recruiter can add candidates.",
                       "status": "APPROVED"}],
        tests=[{"id": "TEST-001", "name": "create candidate", "kind": "api",
                "verifies": ["REQ-001"]}],
        codeMap=[{"artifact": "PAGE-001", "frontend": ["src/app/candidates/page.tsx"]}],
        # A page is coherent only if something composed a tree for it (§34)
        # and there is a design language it was composed against (§37).
        pageLayouts=[{"page": "PAGE-001",
                      "root": {"type": "Stack", "props": {}, "children": []}}],
        designSystem={"colors": {"primary": "#125E8A"},
                      "spacing": {"unit": "4px"},
                      "typography": {"baseSize": "16px"},
                      "radius": {"md": "10px"}},
    )
    report = verify(d)
    assert report.passed, [str(f) for f in report.findings]


def test_the_coherent_fixture_is_a_legal_blueprint():
    """If the fixtures were shapes the schema rejects, every check above would
    be verifying a document that can never exist."""
    from jsonschema import Draft7Validator
    from services.blueprint.service import CONTRACT_PATH

    d = doc(
        roles=[{"id": "ROLE-001", "name": "recruiter"}],
        permissions=[{"id": "PERM-001", "name": "write candidates", "action": "create"}],
        data={"entities": [{"id": "ENTITY-001", "name": "Candidate", "table": "candidates"}]},
        apis=[{"id": "API-001", "method": "POST", "path": "/api/candidates",
               "entity": "ENTITY-001", "permission": "PERM-001"}],
        pages=[{"id": "PAGE-001", "name": "Candidates", "route": "/candidates",
                "purpose": "Manage candidates.", "users": ["ROLE-001"],
                "actions": ["create"], "data": {"primaryEntity": "ENTITY-001"},
                "requirements": ["REQ-001"], "status": "IMPLEMENTED"}],
        requirements=[{"id": "REQ-001", "description": "Recruiter can add candidates.",
                       "status": "APPROVED"}],
        tests=[{"id": "TEST-001", "name": "create candidate", "kind": "api",
                "verifies": ["REQ-001"]}],
        codeMap=[{"artifact": "PAGE-001", "frontend": ["src/app/candidates/page.tsx"]}],
    )
    validator = Draft7Validator(json.loads(CONTRACT_PATH.read_text("utf-8")))
    assert list(validator.iter_errors(d)) == []


# --- one test per §75 edge --------------------------------------------------

def test_page_action_without_an_endpoint_is_caught():
    d = doc(
        data={"entities": [{"id": "ENTITY-001", "name": "Candidate", "table": "c"}]},
        pages=[{"id": "PAGE-001", "name": "P", "route": "/c", "purpose": "x",
                "actions": ["create"], "data": {"primaryEntity": "ENTITY-001"}}],
    )
    hits = verify(d, edges=("Page↔API",)).findings
    assert len(hits) == 1 and "POST" in hits[0].detail


def test_endpoint_on_an_unknown_entity_is_caught():
    d = doc(apis=[{"id": "API-001", "method": "GET", "path": "/x", "entity": "ENTITY-404"}])
    hits = verify(d, edges=("API↔Database",)).findings
    assert len(hits) == 1 and "ENTITY-404" in hits[0].detail


def test_page_for_a_nonexistent_role_is_caught():
    d = doc(pages=[{"id": "PAGE-001", "name": "P", "route": "/c", "purpose": "x",
                    "users": ["ROLE-404"]}])
    hits = verify(d, edges=("Page↔Permission",)).findings
    assert len(hits) == 1 and "ROLE-404" in hits[0].detail


def test_unguarded_mutating_endpoint_is_caught():
    d = doc(apis=[{"id": "API-001", "method": "DELETE", "path": "/api/candidates"}])
    hits = verify(d, edges=("API↔Permission",)).findings
    assert len(hits) == 1 and "no permission" in hits[0].detail


def test_read_endpoint_needs_no_permission():
    d = doc(apis=[{"id": "API-001", "method": "GET", "path": "/api/candidates"}])
    assert verify(d, edges=("API↔Permission",)).passed


def test_rule_governing_a_missing_artifact_is_caught():
    d = doc(businessRules=[{"id": "RULE-001", "name": "r", "statement": "s",
                            "appliesTo": ["FLOW-404"]}])
    hits = verify(d, edges=("Workflow↔BusinessRule",)).findings
    assert len(hits) == 1 and "FLOW-404" in hits[0].detail


def test_workflow_mutating_an_entity_with_no_write_endpoint_is_caught():
    d = doc(
        data={"entities": [{"id": "ENTITY-001", "name": "Candidate", "table": "c"}]},
        workflows=[{"id": "FLOW-001", "name": "hire",
                    "trigger": {"kind": "manual"},
                    "steps": [{"key": "s1", "name": "save", "type": "action",
                               "entity": "ENTITY-001"}]}],
    )
    hits = verify(d, edges=("Workflow↔API",)).findings
    assert len(hits) == 1 and "no write endpoint" in hits[0].detail


def test_workflow_launched_from_a_missing_page_is_caught():
    d = doc(workflows=[{"id": "FLOW-001", "name": "w", "trigger": {"kind": "manual"},
                        "launchedFrom": ["PAGE-404"]}])
    hits = verify(d, edges=("Workflow↔API",)).findings
    assert any("PAGE-404" in h.detail for h in hits)


def test_a_design_system_too_thin_to_compose_against_is_caught():
    """This checked `components` against `uiRegistry` — one LLM section
    against another, both authored by a node that no longer exists. The
    failure it never covered is the one that shipped: a design system so thin
    that `project_design_tokens` emits almost nothing and every page comes out
    unstyled, with no error anywhere, because a missing token is only absence.
    """
    d = doc(designSystem={"colors": {"primary": "#125E8A"}})
    hits = verify(d, edges=("Design↔DesignSystem",)).findings
    assert {h.artifact_id for h in hits} == {"spacing", "typography", "radius"}

    d = doc(designSystem={})
    hits = verify(d, edges=("Design↔DesignSystem",)).findings
    assert len(hits) == 1 and "does not exist" in hits[0].detail


def test_approved_requirement_nothing_claims_is_caught():
    d = doc(requirements=[{"id": "REQ-001", "description": "x", "status": "APPROVED"}])
    hits = verify(d, edges=("Requirement↔Code",)).findings
    assert len(hits) == 1 and "no artifact claims" in hits[0].detail


def test_proposed_requirement_is_not_yet_owed_an_implementation():
    d = doc(requirements=[{"id": "REQ-001", "description": "x", "status": "PROPOSED"}])
    assert verify(d, edges=("Requirement↔Code", "Requirement↔Test")).passed


def test_untested_requirement_is_caught():
    d = doc(requirements=[{"id": "REQ-001", "description": "x", "status": "APPROVED"}])
    hits = verify(d, edges=("Requirement↔Test",)).findings
    assert len(hits) == 1 and "no test" in hits[0].detail


def test_artifact_claiming_to_be_built_with_no_codemap_is_caught():
    d = doc(pages=[{"id": "PAGE-001", "name": "P", "route": "/c", "purpose": "x",
                    "status": "VERIFIED"}])
    hits = verify(d, edges=("Blueprint↔Implementation",)).findings
    assert len(hits) == 1 and "codeMap" in hits[0].detail


def test_deprecated_artifacts_are_not_held_to_account():
    d = doc(apis=[{"id": "API-001", "method": "DELETE", "path": "/x",
                   "status": "DEPRECATED"}])
    assert verify(d, edges=("API↔Permission",)).passed


# --- §74: routing and the per-requirement rollup ----------------------------

def test_findings_route_to_the_responsible_agent():
    d = doc(
        apis=[{"id": "API-001", "method": "DELETE", "path": "/x"}],
        pages=[{"id": "PAGE-001", "name": "C", "route": "/c",
                "purpose": "x"}],
    )
    tasks = verify(d).repair_tasks()
    assert tasks["api"][0].artifact_id == "API-001"
    assert "PAGE-001" in {t.artifact_id for t in tasks["page_design"]}


def test_requirement_verdict_matches_the_section_74_shape():
    d = doc(requirements=[{"id": "REQ-001", "description": "Admin can deactivate a tag.",
                           "status": "APPROVED"}])
    verdict = requirement_verdict(d, "REQ-001")
    assert verdict["result"] == "FAILED"
    assert verdict["facets"]["Requirement↔Test"]["ok"] is False


def test_summary_states_what_it_did_not_verify():
    d = doc()
    assert "codeMap entries are not checked against files" in verify(d).summary()["unverified"]


# --- §76: flag, never fix ---------------------------------------------------

def test_apply_findings_marks_out_of_sync(svc):
    svc.upsert("data.entities", {"name": "Candidate", "table": "candidates"},
               natural_key=entity_key("Candidate"))
    svc.upsert("apis", {"method": "DELETE", "path": "/api/candidates",
                        "entity": "ENTITY-001"}, natural_key="API:DELETE /api/candidates")

    report = verify(svc.doc, edges=("API↔Permission",))
    marked = apply_findings(svc, report)

    assert marked == ["API-001"]
    art = svc.find("API-001")[1]
    assert art["status"] == "OUT_OF_SYNC"
    assert "API↔Permission" in art["syncNote"]
    svc.validate()


def test_verification_changes_status_and_nothing_else(svc):
    """The whole point. If this test ever fails, a repair has crept back in."""
    svc.upsert("apis", {"method": "DELETE", "path": "/api/x"},
               natural_key="API:DELETE /api/x")
    before = json.loads(json.dumps(svc.doc))

    apply_findings(svc, verify(svc.doc))

    after = svc.doc
    for i, api in enumerate(after["apis"]):
        stripped = {k: v for k, v in api.items() if k not in ("status", "syncNote")}
        original = {k: v for k, v in before["apis"][i].items()
                    if k not in ("status", "syncNote")}
        assert stripped == original, "verification edited artifact content"
    assert after["version"] == before["version"], "verification versioned the Blueprint"


def test_verify_itself_is_pure(svc):
    svc.upsert("apis", {"method": "DELETE", "path": "/api/x"},
               natural_key="API:DELETE /api/x")
    snapshot = json.loads(json.dumps(svc.doc))
    verify(svc.doc)
    assert svc.doc == snapshot


def test_findings_for_absent_artifacts_do_not_invent_them(svc):
    from services.blueprint.verification import Finding, VerificationReport

    report = VerificationReport(findings=[
        Finding("API↔Database", "phantom", artifact_id="API-999", section="apis")
    ])
    assert apply_findings(svc, report) == []
    assert svc.doc.get("apis", []) == []


# --- edges added by the migration ledger ------------------------------------

def test_nav_entry_pointing_at_a_missing_page_is_caught():
    """Migrated from nav_route_reconcile_guard / navigate_target_guard — the
    dead 'View details' button class."""
    d = doc(navigation={"tree": [{"label": "Candidates", "page": "PAGE-404"}]})
    hits = verify(d, edges=("Navigation↔Page",)).findings
    assert len(hits) == 1 and "PAGE-404" in hits[0].detail


def test_unreachable_list_page_is_caught():
    d = doc(pages=[{"id": "PAGE-001", "name": "P", "route": "/c", "purpose": "x",
                    "pattern": "entity_list"}],
            navigation={"tree": []})
    hits = verify(d, edges=("Navigation↔Page",)).findings
    assert len(hits) == 1 and "not reachable" in hits[0].detail


def test_detail_pages_need_no_nav_entry():
    """Detail routes are reached from their list; flagging them would be noise."""
    d = doc(pages=[{"id": "PAGE-001", "name": "P", "route": "/c/[id]", "purpose": "x",
                    "pattern": "master_detail"}],
            navigation={"tree": []})
    assert verify(d, edges=("Navigation↔Page",)).passed


def test_orphan_manual_workflow_is_caught():
    """Migrated from orphan_wiring_pass, which used to invent a launcher form."""
    d = doc(workflows=[{"id": "FLOW-001", "name": "approve",
                        "trigger": {"kind": "manual"}}])
    hits = verify(d, edges=("Page↔Workflow",)).findings
    assert len(hits) == 1 and "no page that launches it" in hits[0].detail


def test_event_triggered_workflow_needs_no_launcher():
    d = doc(workflows=[{"id": "FLOW-001", "name": "onCreate",
                        "trigger": {"kind": "event"}}])
    assert verify(d, edges=("Page↔Workflow",)).passed


def test_page_action_targeting_a_missing_workflow_is_caught():
    d = doc(pages=[{"id": "PAGE-001", "name": "P", "route": "/c", "purpose": "x",
                    "actions": ["FLOW-404"]}])
    hits = verify(d, edges=("Page↔Workflow",)).findings
    assert len(hits) == 1 and "FLOW-404" in hits[0].detail


# --- Widget↔DataSource: the last migrated edge ------------------------------

def widget_doc(**over):
    w = {"id": "WIDGET-001", "page": "PAGE-001", "kind": "metric",
         "label": "Utilization Rate", "unit": "number",
         "dataSource": {"op": "aggregate", "entity": "ENTITY-001",
                        "aggregation": "count"}}
    w.update(over)
    return doc(
        pages=[{"id": "PAGE-001", "name": "D", "route": "/", "purpose": "x"}],
        data={"entities": [{"id": "ENTITY-001", "name": "LeaveBalance",
                            "table": "leave_balances",
                            "fields": [{"name": "days", "type": "integer"}]}]},
        widgets=[w],
    )


def test_a_magnitude_shown_as_a_percent_is_caught():
    """The 1,000%-utilisation bug: a count rendered as a ratio."""
    hits = verify(widget_doc(unit="percent"), edges=("Widget↔DataSource",)).findings
    assert len(hits) == 1 and "fabricated number" in hits[0].detail


def test_a_ratio_may_be_shown_as_a_percent():
    d = widget_doc(unit="percent", dataSource={"op": "aggregate", "entity": "ENTITY-001",
                                               "aggregation": "avg", "field": "days"})
    assert verify(d, edges=("Widget↔DataSource",)).passed


def test_widget_bound_to_an_unknown_entity_is_caught():
    d = widget_doc(dataSource={"op": "aggregate", "entity": "ENTITY-404",
                               "aggregation": "count"})
    hits = verify(d, edges=("Widget↔DataSource",)).findings
    assert len(hits) == 1 and "ENTITY-404" in hits[0].detail


def test_widget_aggregating_a_nonexistent_column_is_caught():
    d = widget_doc(dataSource={"op": "aggregate", "entity": "ENTITY-001",
                               "aggregation": "sum", "field": "nope"})
    hits = verify(d, edges=("Widget↔DataSource",)).findings
    assert any("not a column" in h.detail for h in hits)


def test_non_count_aggregation_without_a_field_is_caught():
    d = widget_doc(dataSource={"op": "aggregate", "entity": "ENTITY-001",
                               "aggregation": "sum"})
    hits = verify(d, edges=("Widget↔DataSource",)).findings
    assert any("needs a field" in h.detail for h in hits)


def test_widget_findings_route_to_page_design():
    tasks = verify(widget_doc(unit="percent")).repair_tasks()
    assert tasks["page_design"][0].artifact_id == "WIDGET-001"


# --- relationships: reachable since data_model was widened ------------------

def test_relationship_naming_a_missing_entity_is_caught():
    """Migrated from fk_source_guard, which repaired the column instead."""
    d = doc(data={"entities": [{"id": "ENTITY-001", "name": "Candidate", "table": "c"}],
                  "relationships": [{"from": "ENTITY-001", "to": "ENTITY-404",
                                     "kind": "one_to_many"}]})
    hits = verify(d, edges=("API↔Database",)).findings
    assert len(hits) == 1 and "ENTITY-404" in hits[0].detail


def test_relationship_field_that_is_not_a_column_is_caught():
    """Migrated from fk_type_guard: the mismatch is reported, not rewritten."""
    d = doc(data={"entities": [
        {"id": "ENTITY-001", "name": "Application", "table": "a",
         "fields": [{"name": "candidateId", "type": "uuid"}]},
        {"id": "ENTITY-002", "name": "Candidate", "table": "c",
         "fields": [{"name": "id", "type": "uuid"}]}],
        "relationships": [{"from": "ENTITY-001", "to": "ENTITY-002",
                           "kind": "one_to_many", "fromField": "candidate_id"}]})
    hits = verify(d, edges=("API↔Database",)).findings
    assert any("not a column" in h.detail for h in hits)


def test_a_coherent_relationship_passes():
    d = doc(data={"entities": [
        {"id": "ENTITY-001", "name": "Application", "table": "a",
         "fields": [{"name": "candidateId", "type": "uuid"}]},
        {"id": "ENTITY-002", "name": "Candidate", "table": "c",
         "fields": [{"name": "id", "type": "uuid"}]}],
        "relationships": [{"from": "ENTITY-001", "to": "ENTITY-002",
                           "kind": "one_to_many", "fromField": "candidateId",
                           "toField": "id"}]})
    assert verify(d, edges=("API↔Database",)).passed


def test_constraint_on_a_missing_entity_is_caught():
    d = doc(data={"entities": [], "constraints": [
        {"entity": "ENTITY-404", "kind": "unique", "expression": "email"}]})
    hits = verify(d, edges=("API↔Database",)).findings
    assert len(hits) == 1 and "unknown entity" in hits[0].detail


def test_relationship_findings_route_to_the_data_model_agent():
    d = doc(data={"entities": [], "relationships": [
        {"from": "ENTITY-001", "to": "ENTITY-002", "kind": "one_to_many"}]})
    assert "data_model" in verify(d, edges=("API↔Database",)).repair_tasks()
