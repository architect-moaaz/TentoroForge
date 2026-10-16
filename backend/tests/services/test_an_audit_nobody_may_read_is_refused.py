"""A trail with no reviewers is write-only and refused; an `audit_trail`
page is for the reviewers and needs a trail (2026-10-12)."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidAudit, check_audit

DOC = {"roles": [{"id": "ROLE-001", "name": "Compliance"}, {"id": "ROLE-002", "name": "Clerk"}],
       "data": {"entities": [{"id": "ENTITY-001", "name": "Invoice"}]},
       "security": {"audit": {"level": "writes", "reviewers": ["ROLE-001"]}}}


def _security(audit: dict) -> AgentResult:
    return AgentResult(task_id="T", agent="security", proposals=[ArtifactProposal(section="security", natural_key="security", body={"audit": audit})])


def _page(users: list[str]) -> AgentResult:
    return AgentResult(task_id="T", agent="page_design", proposals=[ArtifactProposal(
        section="pages", natural_key="Audit trail", body={"name": "Audit trail", "route": "/audit", "pattern": "audit_trail", "users": users})])


def test_a_trail_with_reviewers_who_are_roles_passes():
    check_audit(_security({"level": "regulated", "reviewers": ["ROLE-001"], "reasonRequired": ["ENTITY-001"]}), DOC)
    check_audit(_security({"level": "none"}), DOC)
    check_audit(_page(["ROLE-001"]), DOC)


@pytest.mark.parametrize("audit,said", [
    ({"level": "writes", "reviewers": []}, "write-only"),
    ({"level": "writes", "reviewers": ["ROLE-009"]}, "not a declared role"),
    ({"level": "regulated", "reviewers": ["ROLE-001"], "reasonRequired": ["ENTITY-404"]}, "names RECORD TYPES by entity id"),
])
def test_a_policy_nobody_can_act_on_is_refused(audit, said):
    with pytest.raises(InvalidAudit, match=said):
        check_audit(_security(audit), DOC)


def test_an_audit_screen_is_for_the_reviewers_and_needs_a_trail():
    with pytest.raises(InvalidAudit, match="for the reviewers"):
        check_audit(_page(["ROLE-002"]), DOC)
    with pytest.raises(InvalidAudit, match="needs a trail"):
        check_audit(_page(["ROLE-001"]), {**DOC, "security": {"audit": {"level": "none"}}})


def test_roles_declared_in_the_same_reply_are_known():
    """The access step writes `roles` beside `security`; reviewers it creates
    in that reply were refused as undeclared (60v142ju, 2026-10-12)."""
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, check_audit
    res = AgentResult(task_id="T", agent="security", proposals=[
        ArtifactProposal(section="roles", natural_key="Supervisor", body={"name": "Supervisor"}),
        ArtifactProposal(section="security", natural_key="security", body={"audit": {"level": "writes", "reviewers": ["Supervisor"]}})])
    check_audit(res, {"data": {"entities": [{"id": "ENTITY-001", "name": "Submission"}]}})


def test_reasons_name_record_types_and_say_which_exist():
    import pytest
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidAudit, check_audit
    res = AgentResult(task_id="T", agent="security", proposals=[
        ArtifactProposal(section="roles", natural_key="Supervisor", body={"name": "Supervisor"}),
        ArtifactProposal(section="security", natural_key="security", body={"audit": {
            "level": "regulated", "reviewers": ["Supervisor"], "reasonRequired": ["VIEW_SUBMISSION"]}})])
    with pytest.raises(InvalidAudit) as e:
        check_audit(res, {"data": {"entities": [{"id": "ENTITY-001", "name": "Submission"}]}})
    assert "not actions" in str(e.value) and "ENTITY-001 (Submission)" in str(e.value)


def test_a_trail_screen_planned_before_access_waits_and_then_holds_access_to_it():
    import pytest
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidAudit, check_audit
    page = ArtifactProposal(section="pages", natural_key="Audit Trail", body={"name": "Audit Trail", "pattern": "audit_trail", "users": []})
    check_audit(AgentResult(task_id="T", agent="page_design", proposals=[page]), {})
    doc = {"pages": [{"id": "PAGE-009", "name": "Audit Trail", "pattern": "audit_trail"}]}
    with pytest.raises(InvalidAudit) as e:
        check_audit(AgentResult(task_id="T", agent="security", proposals=[
            ArtifactProposal(section="roles", natural_key="Admin", body={"name": "Admin"}),
            ArtifactProposal(section="security", natural_key="security", body={"audit": {"level": "none"}})]), doc)
    assert "screens include an audit trail" in str(e.value)


def test_a_screens_users_by_id_match_reviewers_by_name():
    """users ROLE-002/ROLE-003 were refused against reviewers
    Supervisor/SystemAdmin — the same roles, spelled two ways (60v142ju)."""
    import pytest
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidAudit, check_audit
    doc = {"roles": [{"id": "ROLE-001", "name": "Officer"}, {"id": "ROLE-002", "name": "Supervisor"}, {"id": "ROLE-003", "name": "SystemAdmin"}],
           "security": {"audit": {"level": "regulated", "reviewers": ["Supervisor", "SystemAdmin"]}}}
    page = lambda users: AgentResult(task_id="T", agent="page_design", proposals=[  # noqa: E731
        ArtifactProposal(section="pages", natural_key="PAGE:/audit-log", body={"name": "Audit Trail", "pattern": "audit_trail", "users": users})])
    check_audit(page(["ROLE-002", "ROLE-003"]), doc)
    check_audit(page(["Supervisor"]), doc)
    with pytest.raises(InvalidAudit):
        check_audit(page(["ROLE-001"]), doc)


def test_an_audit_screen_that_names_nobody_is_given_the_reviewers():
    """The page writer plans screens and does not author `users` (roles sit on
    sections). FitTrackr (qpqhdugb, 2026-10-16) declared its Audit Log with no
    users and was refused at page_contracts in four builds running; the policy
    already says who reads the trail, so the page is given them."""
    res = _page([])
    check_audit(res, DOC)
    assert res.proposals[0].body["users"] == ["ROLE-001"]

    # Reviewers named by role NAME land on the page as the role's id.
    res = _page([])
    check_audit(res, {**DOC, "security": {"audit": {"level": "writes", "reviewers": ["Compliance"]}}})
    assert res.proposals[0].body["users"] == ["ROLE-001"]

    # Someone who is not a reviewer is still refused; a trail of level none still needs declaring.
    with pytest.raises(InvalidAudit):
        check_audit(_page(["ROLE-002"]), DOC)
    with pytest.raises(InvalidAudit):
        check_audit(_page([]), {**DOC, "security": {"audit": {"level": "none"}}})
