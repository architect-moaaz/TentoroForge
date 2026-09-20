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


LAYOUTS = [
    {"page": "PAGE-002", "root": {"type": "Stack", "children": [
        {"type": "Button", "props": {"label": "Approve Member Verification", "workflow": "FLOW-016"}}]}},
    {"page": "PAGE-008", "root": {"type": "Stack", "children": [
        {"type": "Button", "props": {"label": "Approve", "workflow": "FLOW-016"}}]}},
]


def test_a_control_is_not_offered_to_people_who_cannot_run_it():
    """0l133sp2 put "Approve Member Verification" — the admin's, launched from
    /admin/members/[id] — on /profile, which members open."""
    from services.blueprint.functional_completeness import page_findings

    doc = {**DOC, "pageLayouts": LAYOUTS}
    said = [f for f in page_findings(doc) if f["rule"] == "workflow-audience-mismatch"]
    assert [f["page"] for f in said] == ["PAGE-002"]
    assert "/admin/members/[id]" in said[0]["detail"]


def test_the_page_a_workflow_is_launched_from_has_something_that_runs_it():
    """Nothing on /profile ran Submit Identity Verification, the only page
    that launches it — so the member could not send their document."""
    from services.blueprint.functional_completeness import launcher_findings

    doc = {**DOC, "pageLayouts": LAYOUTS}
    said = [f for f in launcher_findings(doc) if f["rule"] == "launcher-without-control"]
    assert [f["page"] for f in said] == ["PAGE-002"]
    assert "FLOW-018" in said[0]["detail"]
    # The page written as code carries its controls in the code.
    coded = {**doc, "pageCode": [{"page": "PAGE-002", "view": "<WorkflowForm workflow={workflows.submitIdentityVerification} />"}]}
    assert not [f for f in launcher_findings(coded) if f["page"] == "PAGE-002"]


def test_a_run_missing_what_it_needs_is_refused_before_it_writes():
    """The photo column was overwritten with NULL and the run said completed."""
    import tempfile

    out = Path(tempfile.mkdtemp())
    wf = {**FLOWS[1], "inputs": [{"name": "member", "kind": "record", "entity": "ENTITY-001"},
                                 {"name": "idDocumentPhoto", "kind": "field", "type": "image"},
                                 {"name": "note", "kind": "field", "type": "string", "required": False}]}
    project_workflows({**DOC, "workflows": [wf]}, out)
    defn = json.loads(next(out.rglob("submit-identity-verification.json")).read_text())
    assert defn["requiredInputs"] == ["member", "idDocumentPhoto"]
    engine = (Path(__file__).resolve().parents[2] / "templates/runtime/workflows/index.ts").read_text()
    assert "missingRequiredInputs" in engine and "refused: true" in engine


QUEUE = {"id": "PAGE-007", "route": "/admin/members", "name": "Member Verification Queue",
         "users": ["ROLE-002"], "access": "role_restricted",
         "data": {"primaryEntity": "ENTITY-001"},
         "views": [{"key": "pending", "label": "Pending review", "isDefault": True,
                    "filter": {"kycStatus": "pending"}}]}
MEMBER = {"id": "ENTITY-001", "name": "Member", "table": "members",
          "fields": [{"name": "kycStatus", "type": "enum"}]}
SUBMIT = {**FLOWS[1], "steps": [
    {"key": "save", "type": "action", "entity": "ENTITY-001",
     "config": {"actionType": "db_update", "table": "members",
                "values": {"kycStatus": "pending", "idDocumentPhoto": "{{idDocumentPhoto}}"}}},
    {"key": "notify", "type": "action",
     "config": {"actionType": "send_notification", "recipientRole": "ROLE-002",
                "message": "awaiting verification"}}]}


def test_the_queue_a_role_is_sent_to_opens_on_what_is_waiting():
    from services.blueprint.functional_completeness import queue_findings

    doc = {**DOC, "data": {"entities": [MEMBER]}, "workflows": [SUBMIT],
           "pages": [{**QUEUE, "views": []}]}
    said = queue_findings(doc)
    assert [f["rule"] for f in said] == ["queue-without-its-state"]
    assert "kycStatus='pending'" in said[0]["detail"]
    # Declared, and nothing more is asked.
    assert not queue_findings({**doc, "pages": [QUEUE]})


def test_a_declared_view_that_the_composer_dropped_is_a_finding():
    """0l133sp2 declared "Pending review" as the default and the composed tree
    was a plain table of every member — the submission was invisible."""
    from services.blueprint.functional_completeness import page_findings

    plain = {"page": "PAGE-007", "dataSources": [{"name": "member", "entity": "Member", "op": "list"}],
             "root": {"type": "Stack", "children": [
                 {"type": "Table", "props": {"data": "{{member}}", "columns": [{"key": "email"}]}}]}}
    doc = {**DOC, "data": {"entities": [MEMBER]}, "pages": [QUEUE], "pageLayouts": [plain]}
    said = [f for f in page_findings(doc) if f["rule"] == "views-not-composed"]
    assert [f["page"] for f in said] == ["PAGE-007"]
    assert "Pending review" in said[0]["detail"]

    kept = {**plain, "dataSources": [{"name": "member", "entity": "Member", "op": "list",
                                      "filter": {"kycStatus": "pending"}}],
            "root": {"type": "Stack", "children": [
                {"type": "FilterBar", "props": {"savedViews": [{"id": "pending", "label": "Pending review",
                                                                "filters": {"kycStatus": "pending"}}]}},
                {"type": "Table", "props": {"data": "{{member}}", "columns": [{"key": "email"}]}}]}}
    assert not [f for f in page_findings({**doc, "pageLayouts": [kept]})
                if f["rule"] == "views-not-composed"]
