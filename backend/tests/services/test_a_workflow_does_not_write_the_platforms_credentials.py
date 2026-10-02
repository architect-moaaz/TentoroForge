"""LabConnect's FLOW-001 wrote `passwordHash` into the platform's users table.

The projector folds that field into the platform's `password` column, so the
shipped table never had it, and the only thing that noticed was the engine dry
run at `assemble` — forty minutes in, where no repair round reaches. Refused at
the author now, the way every other engine refusal is.
"""
import json

import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidWorkflowStep, check_workflow_steps,
)
from services.blueprint.functional_completeness import platform_write_findings


def _wf(step_values, table="users", action="db_insert", name="Create User Account"):
    return {"id": "FLOW-001", "name": name, "status": "ACTIVE", "steps": [
        {"key": "insert_user", "type": "action",
         "config": {"actionType": action, "table": table, "values": step_values}}]}


@pytest.mark.parametrize("column", ["passwordHash", "password", "password_hash",
                                    "hashedPassword", "salt"])
def test_a_credential_column_is_refused_whatever_it_is_called(column):
    [finding] = platform_write_findings({"workflows": [_wf({column: "{{password}}"})]})
    assert finding["rule"] == "platform-credential-write"
    assert column in finding["detail"] and "sign-up" in finding["detail"]


def test_a_folded_field_is_told_the_column_the_platform_ships():
    [finding] = platform_write_findings({"workflows": [_wf({"fullName": "{{n}}"})]})
    assert finding["rule"] == "platform-column-renamed"
    assert "'name'" in finding["detail"]


def test_an_ordinary_table_is_not_the_platforms_business():
    """`labs` is the app's own table; what it stores is the Blueprint's call."""
    assert platform_write_findings({"workflows": [_wf({"passwordHash": "x"}, table="labs")]}) == []


def test_reading_the_users_table_is_fine():
    assert platform_write_findings(
        {"workflows": [_wf({"email": "{{e}}"}, action="db_query")]}) == []


def test_the_author_is_refused_when_the_step_is_written():
    """Not at `assemble`: here, where the agent can be asked again."""
    result = AgentResult(task_id="T", agent="workflow", proposals=[
        ArtifactProposal(section="workflows", natural_key="FLOW-001",
                         body=_wf({"email": "{{email}}", "passwordHash": "{{password}}"}))])
    with pytest.raises(InvalidWorkflowStep) as refused:
        check_workflow_steps(result, {"data": {"entities": []}})
    assert "passwordHash" in str(refused.value)
