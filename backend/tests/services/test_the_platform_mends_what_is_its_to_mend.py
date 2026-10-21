"""What a reply cannot know or does not matter is mended by Forge, not asked
again: an id for a role made in the same reply, a bookkeeping field the
contract does not have. Every check's fault is said at once, and the last try
never ends worse than the one before. From Refund And Chargeback's access step
(f7kxusg6, forge-v3 2026-10-20): three tries, three different faults, stopped."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.blueprint import agent_contract as ac
from services.blueprint import orchestrator as orch
from services.blueprint.agent_contract import AgentResult, ArtifactProposal


def test_a_field_the_contract_does_not_have_is_left_out_and_a_name_becomes_its_id():
    doc = {"roles": [{"id": "ROLE-001", "name": "FrontOfficeManager"}, {"id": "ROLE-002", "name": "Administrator"}],
           "security": {"confidence": 0.9, "status": "PROPOSED", "authentication": "email_password",
                        "signIn": {"sso": [{"id": "entra", "name": "Entra", "kind": "oidc", "provider": "entra",
                                            "integration": "INT-001",
                                            "roleFrom": {"claim": "groups",
                                                         "map": {"FOM": "Front Office Manager", "Admin": "Administrator",
                                                                 "Ghost": "NobodyAtAll"}}}]}}}
    said = ac.tidy_for_contract(doc, {"security"})
    sec = doc["security"]
    assert "confidence" not in sec and "status" not in sec
    assert sec["signIn"]["sso"][0]["roleFrom"]["map"] == {"FOM": "ROLE-001", "Admin": "ROLE-002", "Ghost": "NobodyAtAll"}
    assert any("left out confidence, status" in s for s in said)
    # Only the sections the reply wrote are touched.
    other = {"roles": doc["roles"], "requirements": [{"id": "REQ-001", "issues": ["x"]}]}
    ac.tidy_for_contract(other, {"security"})
    assert other["requirements"][0]["issues"] == ["x"]


def test_every_refusal_of_a_reply_is_said_at_once():
    a = ac.InvalidAudit("audit fault", settle=lambda: ["a"])
    b = ac.InvalidSignIn("sign-in fault", settle=lambda: ["b"])
    both = ac.SeveralRefusals([a, b])
    assert "InvalidAudit: audit fault" in str(both) and "InvalidSignIn: sign-in fault" in str(both)
    assert both.settle() == ["a", "b"]
    assert ac.SeveralRefusals([a, ac.InvalidOwnershipRule("leak")]).settle is None


def test_a_sign_in_named_unlike_its_keys_takes_the_name_its_keys_have():
    sec = {"signIn": {"sso": [{"id": "entra_criterion", "name": "Entra", "kind": "oidc", "provider": "entra",
                               "integration": "INT-001", "provisioning": "invite_only"}]}}
    result = AgentResult(task_id="t", agent="security", proposals=[ArtifactProposal(section="security", natural_key="security", body=sec)])
    doc = {"integrations": [{"id": "INT-001", "kind": "auth", "serves": "sign_in",
                             "secretRefs": ["SSO_ENTRA_CLIENT_ID", "SSO_ENTRA_CLIENT_SECRET", "SSO_ENTRA_ISSUER"]}]}
    with pytest.raises(ac.InvalidSignIn) as refused:
        ac.check_sign_in(result, doc)
    refused.value.settle()
    assert sec["signIn"]["sso"][0]["id"] == "entra"


def test_a_record_type_named_by_its_name_in_the_audit_is_that_record_type():
    sec = {"audit": {"level": "writes", "reviewers": ["Administrator"], "reasonRequired": ["ApprovalDecision", "Nothing"]}}
    result = AgentResult(task_id="t", agent="security", proposals=[
        ArtifactProposal(section="security", natural_key="security", body=sec),
        ArtifactProposal(section="roles", natural_key="Administrator", body={"name": "Administrator"})])
    doc = {"data": {"entities": [{"id": "ENTITY-008", "name": "ApprovalDecision"}]}}
    with pytest.raises(ac.InvalidAudit) as refused:
        ac.check_audit(result, doc)
    refused.value.settle()
    assert sec["audit"]["reasonRequired"] == ["ENTITY-008"]


def test_the_last_try_never_ends_worse_than_the_one_before(monkeypatch, tmp_path):
    svc = SimpleNamespace(output_dir=str(tmp_path), doc={})
    earlier = AgentResult(task_id="t2", agent="security")
    last = AgentResult(task_id="t3", agent="security")
    applied = SimpleNamespace(applied=True, artifacts=["X"], change_requests=[], needs_clarification=False)

    def apply(svc_, outcome, **kw):
        if outcome is last:
            raise ac.InvalidOwnershipRule("nine format faults, no way through")
        if not getattr(outcome, "settled_checks", None):
            raise ac.InvalidSignIn("sign-in names", settle=lambda: (outcome.settled_checks.add("x"), ["settled earlier"])[1])
        return applied
    monkeypatch.setattr(orch, "apply_agent_result", apply)
    import services.blueprint.refusals as refusals
    monkeypatch.setattr(refusals, "record_refusal", lambda *a, **k: None)
    for name in ("_act_on", "_proposed_identities", "_landed"):
        monkeypatch.setattr(orch, name, lambda *a, **k: [] if name == "_act_on" else None)
    monkeypatch.setattr(orch, "_proposed_identities", lambda *a, **k: set())
    import services.incidents as incidents
    monkeypatch.setattr(incidents, "record", lambda *a, **k: {})
    state = orch._NodeRun(subjects=[""], pending=[""])
    report = orch.RunReport()
    # Try 2: refused with a safe way through, but not the last try — kept, and asked harder.
    got = orch._apply_subject(svc, "security", state, "", earlier, attempt=2, max_attempts=2,
                              commit=True, user_request="", report=report)
    assert got == "retry" and "" in state.escalated and state.settleable[""][0] is earlier
    # Try 3 on the strongest model ends on a refusal with none: the earlier reply is what ships.
    got = orch._apply_subject(svc, "security", state, "", last, attempt=3, max_attempts=2,
                              commit=True, user_request="", report=report)
    assert got == "applied" and report.settled["security"] == ["settled earlier"] and not report.stuck
