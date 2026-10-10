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


def test_a_folded_field_is_written_to_the_column_the_platform_ships():
    """Ecom L1 (2026-10-11): refused for `displayName` ("write name"), then
    refused for `name` ("User has no such field") — the build stopped at the
    opening. The projector folds the field as it folds the table."""
    from services.blueprint.functional_completeness import column_findings
    from services.blueprint.projection import platform_columns
    assert platform_write_findings({"workflows": [_wf({"fullName": "{{n}}"})]}) == []
    assert platform_columns("users", {"displayName": "{{n}}", "phone": "{{p}}"}) == {"name": "{{n}}", "phone": "{{p}}"}
    assert platform_columns("labs", {"displayName": "{{n}}"}) == {"displayName": "{{n}}"}
    doc = {"data": {"entities": [{"id": "E1", "name": "User", "table": "users", "account": True,
                                  "fields": [{"name": "id"}, {"name": "email"}, {"name": "displayName"}]}]},
           "workflows": [_wf({"name": "{{n}}"}, action="db_update"), _wf({"displayName": "{{n}}"}, action="db_update")]}
    assert column_findings(doc) == []


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
