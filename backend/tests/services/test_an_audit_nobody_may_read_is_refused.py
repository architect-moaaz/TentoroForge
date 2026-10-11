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
    ({"level": "regulated", "reviewers": ["ROLE-001"], "reasonRequired": ["ENTITY-404"]}, "not a declared entity"),
])
def test_a_policy_nobody_can_act_on_is_refused(audit, said):
    with pytest.raises(InvalidAudit, match=said):
        check_audit(_security(audit), DOC)


def test_an_audit_screen_is_for_the_reviewers_and_needs_a_trail():
    with pytest.raises(InvalidAudit, match="for the reviewers"):
        check_audit(_page(["ROLE-002"]), DOC)
    with pytest.raises(InvalidAudit, match="needs a trail"):
        check_audit(_page(["ROLE-001"]), {**DOC, "security": {"audit": {"level": "none"}}})
