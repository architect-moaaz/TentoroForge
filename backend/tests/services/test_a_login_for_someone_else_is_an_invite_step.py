"""A process that gives someone else a login does it with `invite_account`:
the account is made by the runtime with a one-time set-password link, so no
process writes `users` or holds a password. The author is told how to write it
and is refused a role the application does not declare. The runtime suite
`run-invite-tests.sh` runs the shipped handler."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidTrigger, check_workflow_triggers
from services.blueprint.executors import NODE_TASKS

DOC = {"roles": [{"id": "ROLE-001", "name": "Operations"}, {"id": "ROLE-002", "name": "Support"}],
       "data": {"entities": [{"id": "ENTITY-001", "name": "Staff"}]}}


def _flow(cfg: dict) -> AgentResult:
    return AgentResult(task_id="T", agent="workflow", proposals=[ArtifactProposal(
        section="workflows", natural_key="Invite staff", body={"name": "Invite staff", "trigger": {"kind": "manual"},
                                                              "steps": [{"key": "invite", "type": "action", "config": cfg}]})])


def test_a_declared_role_or_a_template_to_one_passes():
    check_workflow_triggers(_flow({"actionType": "invite_account", "email": "{{workEmail}}", "role": "Support"}), DOC)
    check_workflow_triggers(_flow({"actionType": "invite_account", "email": "{{workEmail}}", "role": "{{staffRole}}"}), DOC)


@pytest.mark.parametrize("cfg,said", [
    ({"actionType": "invite_account", "role": "Support"}, "names the person's `email`"),
    ({"actionType": "invite_account", "email": "{{workEmail}}", "role": "Admin"}, "declared role's name"),
    ({"actionType": "invite_account", "email": "{{workEmail}}"}, "declared role's name"),
])
def test_an_invite_without_an_address_or_with_an_undeclared_role_is_refused(cfg, said):
    with pytest.raises(InvalidTrigger, match=said):
        check_workflow_triggers(_flow(cfg), DOC)


def test_the_step_writer_is_told_how_to_give_someone_a_login():
    text = " ".join(str(v) for v in NODE_TASKS.values())
    assert "`invite_account`" in text and "never holds a password" in text
