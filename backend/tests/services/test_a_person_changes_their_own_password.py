"""A password is the platform's to change, and the platform offers the step.

E-commerce (forge-v3, 2026-10-09): the declared "Change Password" process
tried to write `passwordHash` on the Customer entity, was refused three
times, and shipped with no steps behind a form that said "Password changed".
The catalogue could not express it. Now it can: an `action` with
`actionType: set_password`, run by the engine on the signed-in person's own
login row (proven by run-password-tests.sh); the declarer and the step
author are told; the refusal of a credential write points at it.
"""
from pathlib import Path

from services.catalog import workflow_nodes

_RUNTIME = Path(__file__).resolve().parents[2] / "templates" / "runtime" / "workflows"


def test_the_catalogue_offers_set_password():
    cat = workflow_nodes()
    assert "set_password" in cat.variants("action")
    assert cat.required_groups("action", {"actionType": "set_password"}) == [["actionType"], ["newPassword"]]


def test_a_change_password_step_is_a_configured_node():
    cat = workflow_nodes()
    body = {"id": "FLOW-006", "name": "Change Password", "trigger": {"kind": "manual"},
            "inputs": [{"name": "currentPassword", "kind": "field", "type": "string", "required": True},
                       {"name": "newPassword", "kind": "field", "type": "string", "required": True}],
            "steps": [{"key": "start", "type": "trigger", "config": {"type": "manual"}, "next": ["change"]},
                      {"key": "change", "type": "action",
                       "config": {"actionType": "set_password", "currentPassword": "{{currentPassword}}",
                                  "newPassword": "{{newPassword}}"}, "next": ["done"]},
                      {"key": "done", "type": "end", "config": {}}]}
    assert cat.workflow_errors(body) == []
    bare = {**body, "steps": [body["steps"][0], {"key": "change", "type": "action",
                                                  "config": {"actionType": "set_password"}, "next": ["done"]},
                              body["steps"][2]]}
    assert any("newPassword" in e for e in cat.workflow_errors(bare)), "a step with no new password is refused"


def test_the_engine_and_its_types_carry_the_action():
    assert '"set_password"' in (_RUNTIME / "types.ts").read_text(encoding="utf-8")
    src = (_RUNTIME / "index.ts").read_text(encoding="utf-8")
    assert 'registerActionHandler("set_password"' in src
    assert "bcrypt.compare(current" in src and "bcrypt.hash(next, 12)" in src


def test_the_authors_are_told_and_the_refusal_points_at_it():
    import inspect

    from services.blueprint import executors, functional_completeness
    prompts = inspect.getsource(executors)
    assert "A PASSWORD IS THE PLATFORM'S TO CHANGE" in prompts
    assert "`actionType: set_password`" in prompts
    doc = {"workflows": [{"id": "FLOW-006", "name": "Change Password", "steps": [
        {"key": "update_password", "type": "action",
         "config": {"actionType": "db_update", "table": "users", "where": {"id": "$user.id"},
                    "values": {"passwordHash": "{{newPassword}}"}}}]}]}
    found = functional_completeness.platform_write_findings(doc)
    assert found and found[0]["rule"] == "platform-credential-write"
    assert "set_password" in found[0]["detail"]
