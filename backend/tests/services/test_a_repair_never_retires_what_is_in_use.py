"""A repair is the subject's whole answer — but what the rest of the
Blueprint still uses is not superseded by being left unsaid. pah7lhfz's
access step was rewritten with one role and one permission, and the other
seven roles and forty-five permissions were retired while every screen still
named them (forge-v3, 2026-10-20)."""
from services.blueprint import orchestrator as orch


def test_what_a_live_part_points_at_is_kept_and_keeps_what_it_points_at():
    doc = {
        "roles": [{"id": "ROLE-001", "name": "Requester", "permissions": ["PERM-001"]},
                  {"id": "ROLE-002", "name": "Manager", "permissions": ["PERM-002"]},
                  {"id": "ROLE-003", "name": "Nobody", "permissions": ["PERM-003"]}],
        "permissions": [{"id": "PERM-001"}, {"id": "PERM-002"}, {"id": "PERM-003"}],
        "pages": [{"id": "PAGE-001", "users": ["ROLE-001", "ROLE-002"]}],
    }
    stale = {("id", "roles", "ROLE-001"), ("id", "roles", "ROLE-003"),
             ("id", "permissions", "PERM-001"), ("id", "permissions", "PERM-003"),
             ("keyed", "data.constraints", ("x",))}
    kept = orch._still_in_use(doc, stale)
    # The screen names ROLE-001, which holds PERM-001: both stay. ROLE-003 is
    # named by nothing live, so it and its permission go.
    assert kept == {("id", "roles", "ROLE-001"), ("id", "permissions", "PERM-001")}


def test_a_retired_artifact_is_no_reason_to_keep_another():
    doc = {"roles": [{"id": "ROLE-009", "status": "DEPRECATED", "permissions": ["PERM-009"]}],
           "permissions": [{"id": "PERM-009"}]}
    assert orch._still_in_use(doc, {("id", "permissions", "PERM-009")}) == set()
