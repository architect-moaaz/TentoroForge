"""C-1: the planner deterministically models a persisted, FK-targetable `User`
entity (mapped to the reserved `users` table) with a `role` enum column populated
from `access_control.roles`, and links every actor/person FK column
(`assessorId`/`assignedAssessorId`/`assigneeId`/`reviewerId`/…) to it via
`relations`. This holds even when the LLM omits it (a post-planner normalizer)."""

import copy

from agents.planner import _ensure_actor_user_model


def _ats_plan():
    """A recruitment ATS shaped like output/mc2xgclv: roles name an Assessor and
    an Assessment carries an actor FK column with no relation to any User."""
    return {
        "access_control": {"roles": ["Recruiter", "HiringManager", "Assessor"]},
        "data_models": [
            {
                "name": "Assessment",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "score", "type": "integer", "nullable": True},
                    {"name": "assignedAssessorId", "type": "uuid", "nullable": True},
                ],
            },
            {
                "name": "InterviewFeedback",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "assessorId", "type": "uuid", "nullable": True},
                    {"name": "comments", "type": "text", "nullable": True},
                ],
            },
        ],
        "relations": [],
    }


def _user_model(plan):
    for m in plan.get("data_models") or []:
        if str(m.get("name")) == "User" or str(m.get("table")) == "users":
            return m
    return None


def test_injects_user_entity_with_role_enum():
    plan = _ensure_actor_user_model(_ats_plan())
    user = _user_model(plan)
    assert user is not None, "a User data_model must be injected"
    assert str(user.get("table")) == "users", "User must map to the reserved users table"
    role = next((f for f in user["fields"] if f.get("name") == "role"), None)
    assert role is not None, "User must carry a role column"
    enum = role.get("enum_values") or role.get("enum")
    assert set(enum) == {"Recruiter", "HiringManager", "Assessor"}
    # core profile columns present
    names = {f["name"] for f in user["fields"]}
    assert {"id", "name", "email"}.issubset(names)


def test_links_actor_fk_columns_to_user():
    plan = _ensure_actor_user_model(_ats_plan())
    rels = plan["relations"]

    def _rel(entity, col):
        return next(
            (r for r in rels
             if str(r.get("from")) == entity and str(r.get("foreignKey")) == col),
            None,
        )

    a = _rel("Assessment", "assignedAssessorId")
    assert a is not None and str(a["to"]) == "User"
    f = _rel("InterviewFeedback", "assessorId")
    assert f is not None and str(f["to"]) == "User"


def test_idempotent():
    once = _ensure_actor_user_model(_ats_plan())
    twice = _ensure_actor_user_model(copy.deepcopy(once))
    # same number of User models, role enums, and relations — no duplication
    users = [m for m in twice["data_models"] if str(m.get("table")) == "users"]
    assert len(users) == 1
    roles = [f for f in users[0]["fields"] if f.get("name") == "role"]
    assert len(roles) == 1
    assessor_rels = [r for r in twice["relations"]
                     if str(r.get("foreignKey")) == "assessorId"]
    assert len(assessor_rels) == 1


def test_no_actors_no_roles_unchanged():
    plan = {
        "access_control": {"roles": []},
        "data_models": [
            {"name": "Note", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "body", "type": "text"},
            ]},
        ],
        "relations": [],
    }
    before = copy.deepcopy(plan)
    after = _ensure_actor_user_model(plan)
    assert after == before, "an app with no actors and no roles must be untouched"


def test_existing_domain_relation_on_actor_fk_is_not_overridden():
    """A `managerId` that already points at a domain entity (Employee) keeps its
    target — the normalizer only fills UNLINKED actor FK columns."""
    plan = {
        "access_control": {"roles": ["Admin"]},
        "data_models": [
            {"name": "Employee", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "managerId", "type": "uuid", "nullable": True},
            ]},
        ],
        "relations": [
            {"from": "Employee", "to": "Employee", "type": "many-to-one",
             "foreignKey": "managerId"},
        ],
    }
    after = _ensure_actor_user_model(plan)
    mgr_rels = [r for r in after["relations"] if str(r.get("foreignKey")) == "managerId"]
    assert len(mgr_rels) == 1
    assert str(mgr_rels[0]["to"]) == "Employee"
