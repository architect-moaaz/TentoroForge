"""Chat-Smith reads who does what, and the budget never cuts the pages.

0l133sp2: asked where a member's identity verification goes, Smith said three
times that nothing names a reviewer. Its context carried each workflow as a
name and a purpose, the app description twice, and a 12,000-character cap that
cut the pages and integrations off the end; the architect got 1,200.
"""
from __future__ import annotations

import inspect

from services.smith.engine_blueprint_adapter import to_smith_fields
from services.smith_blueprint import Blueprint
from services.smith_blueprint_context import ContextBudget, blueprint_to_context

DOC = {
    "application": {"name": "T", "description": "A neighbourhood tool-sharing app. " * 60},
    "roles": [{"id": "ROLE-001", "name": "Member"}, {"id": "ROLE-002", "name": "Admin"}],
    "pages": [
        {"id": "PAGE-009", "route": "/profile", "name": "My Profile", "users": ["ROLE-001"]},
        {"id": "PAGE-008", "route": "/admin/members/[id]", "name": "Member Verification Detail",
         "users": ["ROLE-002"], "access": "role_restricted"},
    ],
    "workflows": [
        {"id": "FLOW-018", "name": "Submit Identity Verification", "purpose": "Send an ID for review",
         "launchedFrom": ["PAGE-009"], "trigger": {"kind": "manual"}, "steps": [
             {"key": "save", "type": "action", "config": {"actionType": "db_update", "table": "members",
                                                          "values": {"kycStatus": "pending"}}},
             {"key": "tell", "type": "action", "config": {"actionType": "send_notification",
                                                          "recipientRole": "ROLE-002",
                                                          "message": "A member is awaiting verification"}}]},
        {"id": "FLOW-016", "name": "Approve Member Verification", "purpose": "Approve",
         "launchedFrom": ["PAGE-008"], "trigger": {"kind": "manual"}, "steps": []},
    ],
    "businessRules": [{"name": f"Rule {i}", "statement": "x " * 200} for i in range(40)],
    "data": {"entities": []},
}


def _bp() -> Blueprint:
    bp = Blueprint(project_id="p")
    for key, value in to_smith_fields(DOC).items():
        setattr(bp, key, value)
    return bp


def test_a_workflow_says_who_runs_it_and_who_it_tells():
    text = blueprint_to_context(_bp())
    assert "run by Member from `/profile`" in text
    assert 'notifies Admin: "A member is awaiting verification"' in text
    assert "run by Admin from `/admin/members/[id]`" in text
    assert "Member Verification Detail  · for Admin" in text


def test_the_description_is_said_once():
    text = blueprint_to_context(_bp())
    assert text.count("A neighbourhood tool-sharing app.") <= 60


def test_a_small_budget_shortens_the_prose_and_keeps_the_pages_and_workflows():
    text = blueprint_to_context(_bp(), budget=ContextBudget(max_chars=6000))
    assert "Approve Member Verification" in text and "/admin/members/[id]" in text
    assert "shortened to fit" in text


def test_the_architect_is_given_the_whole_app_not_its_name():
    from services import smith_architect_wire
    assert "ContextBudget(max_chars=1200)" not in inspect.getsource(smith_architect_wire)
