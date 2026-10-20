"""What could only be refused before now ships CLOSED, never open: a secret's
value is never kept, a process that cannot run says it is not available, a
record type whose owner rule cannot be applied is the administrator's alone,
a rule that cannot be checked is written down as not enforced, a screen that
does not render is written after the build — and the after-build fixing
works on each. What has no closed version still stops (2026-10-20)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.blueprint import agent_contract as ac
from services.blueprint.agent_contract import AgentResult, ArtifactProposal

ROLES = [{"id": "ROLE-001", "name": "Front Office Agent", "permissions": ["PERM-001", "PERM-002"]},
         {"id": "ROLE-008", "name": "System Admin", "permissions": ["PERM-001", "PERM-002"]}]
DOC = {"roles": [], "pages": [], "security": {"signupRole": "Front Office Agent"},
       "data": {"entities": [{"id": "ENTITY-001", "name": "Case",
                              "fields": [{"name": "id"}, {"name": "reference"}, {"name": "initiatorId"}]}]}}


def _reply(*proposals) -> AgentResult:
    return AgentResult(task_id="t", agent="x", proposals=[ArtifactProposal(section=s, natural_key=k, body=b)
                                                          for s, k, b in proposals])


def test_a_secret_written_where_its_name_goes_is_never_kept():
    result = _reply(("integrations", "Mews", {"name": "Mews", "kind": "other", "secretRefs": ["sk_live_abc123secretvalue"]}))
    with pytest.raises(ac.InvalidIntegration) as refused:
        ac.check_integrations(result, DOC)
    said = refused.value.settle()
    refs = result.proposals[0].body["secretRefs"]
    assert refs == ["MEWS_API_KEY"] and "sk_live" not in str(result.proposals[0].body)
    assert "MEWS_API_KEY" in said[0]


def test_a_process_that_cannot_run_is_built_switched_off():
    body = {"name": "Refund approval", "trigger": {"kind": "manual"},
            "steps": [{"key": "pay", "type": "action", "config": {"actionType": "no_such_action"}}]}
    result = _reply(("workflows", "Refund approval", body))
    with pytest.raises(ac.InvalidWorkflowStep) as refused:
        ac.check_workflow_steps(result, DOC)
    said = refused.value.settle()
    steps = result.proposals[0].body["steps"]
    assert [s["type"] for s in steps] == ["end"] and steps[0]["config"]["refused"] is True
    assert "not available yet" in steps[0]["config"]["message"] and "switched off" in said[0]
    ac.check_workflow_steps(result, DOC)  # settled


def test_an_automation_whose_trigger_cannot_be_read_is_switched_off_not_the_process():
    body = {"name": "Nightly reconciliation", "trigger": {"kind": "schedule", "cron": "every night"},
            "steps": [{"key": "done", "type": "end", "config": {"refused": False}}]}
    result = _reply(("workflows", "Nightly reconciliation", body))
    with pytest.raises(ac.InvalidTrigger) as refused:
        ac.check_workflow_triggers(result, DOC)
    said = refused.value.settle()
    assert result.proposals[0].body["trigger"]["enabled"] is False
    assert result.proposals[0].body["steps"][0]["key"] == "done" and "trigger is off" in said[0]


def test_a_record_type_whose_owner_rule_cannot_be_applied_is_the_administrators_alone():
    sec = {"ownershipRules": [{"entity": "Case", "column": "ownerId", "kind": "scope", "scope": "user"}]}
    result = _reply(("security", "security", sec),
                    ("roles", "Front Office Agent", dict(ROLES[0], permissions=list(ROLES[0]["permissions"]))),
                    ("roles", "System Admin", dict(ROLES[1], permissions=list(ROLES[1]["permissions"]))),
                    ("permissions", "Read Case", {"id": "PERM-001", "action": "read", "subject": "ENTITY-001"}),
                    ("permissions", "Read Note", {"id": "PERM-002", "action": "read", "subject": "ENTITY-009"}))
    with pytest.raises(ac.InvalidOwnershipRule) as refused:
        ac.check_security(result, DOC)
    said = refused.value.settle()
    roles = {p.body["name"]: p.body["permissions"] for p in result.proposals if p.section == "roles"}
    assert roles == {"Front Office Agent": ["PERM-002"], "System Admin": ["PERM-001", "PERM-002"]}
    assert result.proposals[0].body["ownershipRules"] == []
    assert "Case records are open to the administrator (System Admin) only" in said[0]


def test_an_owner_rule_for_a_record_type_nobody_can_find_has_no_closed_version():
    sec = {"ownershipRules": [{"entity": "Chargeback", "column": "ownerId"}]}
    result = _reply(("security", "security", sec), ("roles", "System Admin", dict(ROLES[1])))
    with pytest.raises(ac.InvalidOwnershipRule) as refused:
        ac.check_security(result, DOC)
    assert refused.value.settle is None


def test_a_rule_the_engine_cannot_read_is_written_down_as_not_enforced():
    rule = {"name": "Big refunds need approval", "kind": "condition_action", "entity": "ENTITY-001",
            "when": "amount >>> 500", "then": [{"type": "show_error", "field": "reference", "message": "x"}]}
    result = _reply(("businessRules", "Big refunds need approval", rule))
    with pytest.raises(ac.InvalidBusinessRule) as refused:
        ac.check_business_rules(result, DOC)
    said = refused.value.settle()
    body = result.proposals[0].body
    assert body["kind"] == "statement" and "when" not in body and body["statement"] == "Big refunds need approval"
    assert "NOT ENFORCED" in said[0]


def test_organisations_settle_stricter_and_without_an_organisation_record_they_stop():
    roles = [{"id": "ROLE-001", "name": "Agent"}, {"id": "ROLE-002", "name": "Owner"}]
    doc = {**DOC, "roles": roles,
           "data": {"entities": [{"id": "ENTITY-002", "name": "Hotel", "tenant": True, "fields": []}]}}
    ten = {"kind": "organisation", "memberRoles": [], "platformRoles": ["Owner", "Ghost"]}
    result = _reply(("security", "security", {"tenancy": ten}))
    with pytest.raises(ac.InvalidTenancy) as refused:
        ac.check_tenancy(result, doc)
    refused.value.settle()
    assert ten["platformRoles"] == ["Owner"] and ten["memberRoles"] == ["Agent"]

    no_org = _reply(("security", "security", {"tenancy": {"kind": "organisation", "memberRoles": ["Agent"]}}))
    with pytest.raises(ac.InvalidTenancy) as refused:
        ac.check_tenancy(no_org, {**doc, "data": {"entities": []}})
    assert refused.value.settle is None


def test_what_was_shipped_closed_is_worked_on_after_the_build(tmp_path):
    from services.blueprint import fix_to_green as ftg
    from services.blueprint import orchestrator as orch
    orch._keep_settled(tmp_path, "workflow_steps", ["Refund approval is built switched off"])
    reds = ftg.settled_reds(str(tmp_path))
    assert reds and reds[0]["cause"] == "settled:workflow_steps"
    group = ftg.by_cause(reds)[0]
    assert group["kind"] == "settled"
    ask = ftg.ask_for(group, {})
    assert "Refund approval is built switched off" in ask and "what the application was meant to be" in ask

    turns = []

    def turn(_pid, _out, ask, **kw):
        turns.append(ask)
        return {"status": "resolved", "edited_paths": ["workflows/refund.json"]}
    ftg._fix([group], str(tmp_path), run_turn=turn, say=lambda _s: None)
    assert turns and ftg.settled_reds(str(tmp_path)) == []
