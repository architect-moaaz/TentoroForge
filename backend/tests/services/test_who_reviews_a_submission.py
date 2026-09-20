"""Who a submission goes to is in the Blueprint, and every reader finds it.

0l133sp2: a member's identity verification notified role "ROLE-002" (the id,
not the name), the built-in admin was seeded as a Member, and Smith — shown
the step but not the roles — answered that nothing names who receives it.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from services.blueprint.account_model import admin_role
from services.blueprint.projection import project_workflows
from services.smith.context import ALWAYS, resolve

ROLES = [{"id": "ROLE-001", "name": "Member"}, {"id": "ROLE-002", "name": "Admin"}]
PAGES = [
    {"id": "PAGE-001", "route": "/tools", "users": ["ROLE-001"], "access": "authenticated"},
    {"id": "PAGE-002", "route": "/profile", "users": ["ROLE-001"], "access": "authenticated"},
    {"id": "PAGE-003", "route": "/rentals", "users": ["ROLE-001", "ROLE-002"], "access": "authenticated"},
    {"id": "PAGE-007", "route": "/admin/members", "name": "Member Verification Queue",
     "users": ["ROLE-002"], "access": "role_restricted"},
    {"id": "PAGE-008", "route": "/admin/members/[id]", "name": "Member Verification Detail",
     "users": ["ROLE-002"], "access": "role_restricted"},
]
FLOWS = [
    {"id": "FLOW-016", "name": "Approve Member Verification", "launchedFrom": ["PAGE-008"],
     "trigger": {"kind": "manual"}, "steps": []},
    {"id": "FLOW-018", "name": "Submit Identity Verification", "launchedFrom": ["PAGE-002"],
     "trigger": {"kind": "manual"}, "steps": [
         {"key": "notify_admin", "name": "Tell the reviewers", "type": "action",
          "config": {"actionType": "send_notification", "recipientRole": "ROLE-002",
                     "message": "A member is awaiting verification"}}]},
]
DOC = {"roles": ROLES, "pages": PAGES, "workflows": FLOWS, "data": {"entities": []},
       "application": {"name": "T"}}


def test_the_admin_account_holds_the_back_office_role_not_the_signup_role():
    assert admin_role(DOC) == "Admin"
    assert admin_role({"roles": [ROLES[0]], "pages": PAGES[:2]}) == "Member", "one role is the admin's too"
    seed = (Path(__file__).resolve().parents[2] / "templates/runtime/seed.ts").read_text()
    assert "row.accountType = ADMIN_ROLE ?? SIGNUP_ROLE" in seed


def test_a_step_names_the_role_the_runtime_compares():
    out = Path(tempfile.mkdtemp())
    project_workflows(DOC, out)
    defn = json.loads(next(out.rglob("submit-identity-verification.json")).read_text())
    node = next(n for n in defn["definition"]["nodes"] if n["id"] == "notify_admin")
    assert node["data"]["config"]["recipientRole"] == "Admin"


def test_smith_is_shown_the_roles_and_what_a_page_in_its_slice_runs():
    assert "roles" in ALWAYS
    ctx = resolve(DOC, "User has sent the Identity verificaiton but to whom its going?")
    assert [r["name"] for r in ctx.blueprint["roles"]] == ["Member", "Admin"]
    names = {w["name"] for w in ctx.blueprint.get("workflows", [])}
    assert "Submit Identity Verification" in names


def test_an_admin_seeded_before_the_role_was_known_is_put_right():
    """0l133sp2 again, a week later: the app HAD the corrected seed and the
    admin was still a Member, because `onConflictDoNothing` never revisits
    the row it skipped. Every seed states the role again."""
    seed = (Path(__file__).resolve().parents[2] / "templates/runtime/seed.ts").read_text()
    existing = seed.split("already exists", 1)[1].split("async function", 1)[0]
    assert "db.update(users" in existing and "roleColumn" in existing
    assert "ADMIN_PASSWORD" not in existing, "a password is the person's, never restated by a seed"
