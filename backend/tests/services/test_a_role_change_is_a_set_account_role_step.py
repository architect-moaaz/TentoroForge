"""Moving an existing person to another role is a `set_account_role` step: the
login's role is the platform's, which no process writes directly. The author is
told how to write it and is refused a step naming nobody or an undeclared role.
The runtime suite `run-invite-tests.sh` runs the shipped handler."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidTrigger, check_workflow_triggers
from services.blueprint.executors import NODE_TASKS
from services.node_config_specs import NODE_CONFIG_SPECS

DOC = {"roles": [{"id": "ROLE-001", "name": "Operations"}, {"id": "ROLE-002", "name": "Support"}],
       "data": {"entities": [{"id": "ENTITY-001", "name": "Staff"}]}}


def _flow(cfg: dict) -> AgentResult:
    return AgentResult(task_id="T", agent="workflow", proposals=[ArtifactProposal(
        section="workflows", natural_key="Change role", body={"name": "Change role", "trigger": {"kind": "manual"},
                                                             "steps": [{"key": "move", "type": "action", "config": cfg}]})])


@pytest.mark.parametrize("cfg", [
    {"actionType": "set_account_role", "userId": "{{person.id}}", "role": "Support"},
    {"actionType": "set_account_role", "email": "{{workEmail}}", "role": "{{newRole}}"},
])
def test_a_person_and_a_declared_role_or_a_template_to_one_passes(cfg):
    check_workflow_triggers(_flow(cfg), DOC)


@pytest.mark.parametrize("cfg,said", [
    ({"actionType": "set_account_role", "role": "Support"}, "names the person's `userId` or `email`"),
    ({"actionType": "set_account_role", "userId": "{{person.id}}", "role": "Admin"}, "declared role's name"),
    ({"actionType": "set_account_role", "userId": "{{person.id}}"}, "declared role's name"),
])
def test_a_role_change_naming_nobody_or_an_undeclared_role_is_refused(cfg, said):
    with pytest.raises(InvalidTrigger, match=said):
        check_workflow_triggers(_flow(cfg), DOC)


def test_the_step_writer_is_told_how_to_move_someone_to_another_role():
    text = " ".join(str(v) for v in NODE_TASKS.values())
    assert "`set_account_role`" in text and "ends their open sessions" in text.replace("\n", " ")


def test_the_step_needs_no_service_settings():
    assert NODE_CONFIG_SPECS["set_account_role"] == []
