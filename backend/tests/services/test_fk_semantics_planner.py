"""Tests for Spec D Wave 2 — planner-authored `column.role` precedence on
fk_semantics.classify_entity_fks. Additive: name-regex fallback intact.
"""
from __future__ import annotations

from services.fk_semantics import classify_entity_fks


def _reg(fields: dict) -> dict:
    return {"entities": {"Task": {"fields": fields}}}


class TestPlannerRoleWins:
    def test_planner_actor_wins_over_name_that_looks_domain(self):
        # `ownerRefId` would normally not match any name regex (no fk, no
        # actor-name match) → default 'plain'. Planner marks it 'actor'
        # and we honor that verbatim.
        reg = _reg({"ownerRefId": {"role": "actor"}})
        roles = classify_entity_fks("Task", reg)
        assert roles["ownerRefId"].role == "actor"

    def test_planner_domain_beats_regex_actor_name(self):
        # `createdById` name would legacy-classify as 'actor'. Planner
        # overrides to 'domain' — respected.
        reg = _reg({"createdById": {"role": "domain"}})
        roles = classify_entity_fks("Task", reg)
        assert roles["createdById"].role == "domain"

    def test_planner_tenancy_wins(self):
        # A `region` field with no fk and no tenancy-name pattern.
        reg = _reg({"region": {"role": "tenancy"}})
        roles = classify_entity_fks("Task", reg)
        assert roles["region"].role == "tenancy"

    def test_planner_assignment_wins(self):
        reg = _reg({"reviewerId": {"role": "assignment"}})
        roles = classify_entity_fks("Task", reg)
        assert roles["reviewerId"].role == "assignment"


class TestLegacyPathPreserved:
    def test_no_role_falls_back_to_actor_regex(self):
        # Name matches _ACTOR_NAME_RE with no fk → legacy 'actor'.
        reg = _reg({"createdById": {}})
        roles = classify_entity_fks("Task", reg)
        assert roles["createdById"].role == "actor"

    def test_no_role_falls_back_to_tenancy_name(self):
        reg = _reg({"workspaceId": {}})
        roles = classify_entity_fks("Task", reg)
        assert roles["workspaceId"].role == "tenancy"

    def test_no_role_no_fk_stays_plain(self):
        reg = _reg({"title": {}})
        roles = classify_entity_fks("Task", reg)
        assert roles["title"].role == "plain"


class TestPlanArgWinsOverRegistry:
    """Spec D W2 — `plan` argument on classify_entity_fks wins over the
    registry's `role`. The plan is the source of truth; the registry is
    a downstream projection that may or may not have carried the field."""

    def test_plan_role_wins_when_registry_silent(self):
        reg = _reg({"ownerRefId": {}})  # registry has no role
        plan = {"entities": {"Task": {"fields": [
            {"name": "ownerRefId", "role": "actor"},
        ]}}}
        roles = classify_entity_fks("Task", reg, plan=plan)
        assert roles["ownerRefId"].role == "actor"

    def test_plan_role_wins_over_registry_role(self):
        # Registry says `domain`; plan says `assignment`. Plan wins.
        reg = _reg({"reviewerId": {"role": "domain"}})
        plan = {"entities": {"Task": {"fields": [
            {"name": "reviewerId", "role": "assignment"},
        ]}}}
        roles = classify_entity_fks("Task", reg, plan=plan)
        assert roles["reviewerId"].role == "assignment"

    def test_plan_none_falls_back_to_registry_then_regex(self):
        # Plan silent; registry silent; name-regex fires → actor.
        reg = _reg({"createdById": {}})
        roles = classify_entity_fks("Task", reg, plan={"entities": {}})
        assert roles["createdById"].role == "actor"

    def test_plan_invalid_role_falls_through_to_registry(self):
        # Plan role is unrecognised; registry-side role wins.
        reg = _reg({"createdById": {"role": "actor"}})
        plan = {"entities": {"Task": {"fields": [
            {"name": "createdById", "role": "bogus"},
        ]}}}
        roles = classify_entity_fks("Task", reg, plan=plan)
        assert roles["createdById"].role == "actor"


class TestFlagShapeTolerance:
    def test_none_role_falls_through(self):
        reg = _reg({"createdById": {"role": None}})
        roles = classify_entity_fks("Task", reg)
        # None isn't in the valid set → legacy actor-name regex fires.
        assert roles["createdById"].role == "actor"

    def test_invalid_role_falls_through(self):
        # A bogus role string ('operator') is NOT in the closed set;
        # the classifier falls through to the legacy path.
        reg = _reg({"createdById": {"role": "operator"}})
        roles = classify_entity_fks("Task", reg)
        assert roles["createdById"].role == "actor"

    def test_non_string_role_falls_through(self):
        reg = _reg({"createdById": {"role": True}})
        roles = classify_entity_fks("Task", reg)
        assert roles["createdById"].role == "actor"
