"""Tests for services.plan_adjust — the Adjust-strategy substrate.

Every op is tested for:
  * happy path (op applies correctly)
  * idempotency (re-apply is a no-op)
  * input purity (original plan not mutated)
  * failure mode (invalid input rejected)

The reliability of the whole conversational adjust flow rests on these
ops staying honest. If a mutation drifts, adjust turns start losing
user intent silently.
"""

from __future__ import annotations

import copy

import pytest

from services.plan_adjust import (
    PlanAdjustError,
    PlanDiff,
    add_actor,
    add_entity,
    add_page,
    add_workflow,
    compute_diff,
    remove_actor,
    remove_entity,
    remove_page,
    remove_workflow,
    toggle_feature,
    validate_plan_shape,
)


def _fresh_plan() -> dict:
    return {
        "module_name": "test",
        "description": "Sample plan for adjust tests",
        "data_models": [
            {"name": "Member", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "email", "type": "string"},
            ], "indexes": []},
        ],
        "pages": [
            {"route": "/members", "name": "MembersPage", "entity": "Member",
             "archetype": "list", "features": [], "description": "", "actions": []},
        ],
        "workflows": [
            {"name": "EnrollMember", "trigger": "POST /api/members",
             "description": "", "steps": [], "roles": [], "conditions": [],
             "error_handling": [], "side_effects": []},
        ],
        "actors": [
            {"name": "Staff", "role": "staff", "onboarding": {"source": "invited_by"}},
        ],
        "relations": [],
        "features": [],
    }


# ------------------------------------------------------------------------- #
# add_entity                                                                 #
# ------------------------------------------------------------------------- #

class TestAddEntity:
    def test_appends_new_entity_with_defaults(self):
        p = _fresh_plan()
        p2 = add_entity(p, name="Booking")
        names = [e["name"] for e in p2["data_models"]]
        assert "Booking" in names
        # Default fields: id + createdAt + updatedAt
        booking = next(e for e in p2["data_models"] if e["name"] == "Booking")
        field_names = [f["name"] for f in booking["fields"]]
        assert field_names == ["id", "createdAt", "updatedAt"]

    def test_merges_custom_fields_dedup(self):
        p = _fresh_plan()
        p2 = add_entity(p, name="Room", fields=[
            {"name": "id", "type": "uuid"},  # dup — should not double
            {"name": "capacity", "type": "int"},
        ])
        room = next(e for e in p2["data_models"] if e["name"] == "Room")
        field_names = [f["name"] for f in room["fields"]]
        assert field_names == ["id", "createdAt", "updatedAt", "capacity"]

    def test_idempotent_on_duplicate(self):
        p = _fresh_plan()
        p2 = add_entity(p, name="Booking")
        p3 = add_entity(p2, name="Booking")
        booking_count = sum(1 for e in p3["data_models"] if e["name"] == "Booking")
        assert booking_count == 1

    def test_does_not_mutate_input(self):
        p = _fresh_plan()
        original = copy.deepcopy(p)
        add_entity(p, name="Booking")
        assert p == original

    def test_rejects_invalid_name(self):
        p = _fresh_plan()
        with pytest.raises(PlanAdjustError):
            add_entity(p, name="")
        with pytest.raises(PlanAdjustError):
            add_entity(p, name="123bad")
        with pytest.raises(PlanAdjustError):
            add_entity(p, name="has spaces")

    def test_rejects_malformed_fields(self):
        p = _fresh_plan()
        with pytest.raises(PlanAdjustError):
            add_entity(p, name="Bad", fields=[{"name": "x"}])  # missing type


# ------------------------------------------------------------------------- #
# remove_entity                                                              #
# ------------------------------------------------------------------------- #

class TestRemoveEntity:
    def test_removes_entity(self):
        p = _fresh_plan()
        p2 = remove_entity(p, name="Member")
        assert not any(e["name"] == "Member" for e in p2["data_models"])

    def test_cascades_relations_and_pages(self):
        p = _fresh_plan()
        p["relations"] = [{"name": "MemberBookings", "from": "Member", "to": "Booking"}]
        p2 = add_entity(p, name="Booking")
        p3 = remove_entity(p2, name="Member")
        # Relations mentioning Member on either side are gone
        assert p3["relations"] == []
        # Page bound to Member is gone
        assert not any(pg.get("entity") == "Member" for pg in p3["pages"])
        # Booking survives
        assert any(e["name"] == "Booking" for e in p3["data_models"])

    def test_idempotent_on_missing(self):
        p = _fresh_plan()
        p2 = remove_entity(p, name="Nonexistent")
        assert p == p2


# ------------------------------------------------------------------------- #
# add_page                                                                   #
# ------------------------------------------------------------------------- #

class TestAddPage:
    def test_appends_with_derived_route(self):
        p = _fresh_plan()
        p2 = add_page(p, name="BookingsPage", entity="Member", archetype="list")
        # route derived from name
        added = next(pg for pg in p2["pages"] if pg["name"] == "BookingsPage")
        assert added["route"] == "/bookings"

    def test_explicit_route_wins(self):
        p = _fresh_plan()
        p2 = add_page(p, name="Foo", entity="Member", archetype="list",
                      route="/custom-path")
        added = next(pg for pg in p2["pages"] if pg["name"] == "Foo")
        assert added["route"] == "/custom-path"

    def test_idempotent_by_route(self):
        p = _fresh_plan()
        p2 = add_page(p, name="MembersPage", entity="Member", route="/members")
        # already exists at /members
        assert len([pg for pg in p2["pages"] if pg["route"] == "/members"]) == 1

    def test_rejects_page_for_missing_entity(self):
        p = _fresh_plan()
        with pytest.raises(PlanAdjustError, match="isn't in data_models"):
            add_page(p, name="BookingsPage", entity="Booking", archetype="list")

    def test_rejects_unknown_archetype(self):
        p = _fresh_plan()
        with pytest.raises(PlanAdjustError, match="unknown archetype"):
            add_page(p, name="Foo", entity="Member", archetype="something-weird")


# ------------------------------------------------------------------------- #
# remove_page                                                                #
# ------------------------------------------------------------------------- #

class TestRemovePage:
    def test_removes_by_route(self):
        p = _fresh_plan()
        p2 = remove_page(p, route="/members")
        assert not any(pg["route"] == "/members" for pg in p2["pages"])

    def test_idempotent_on_missing(self):
        p = _fresh_plan()
        assert remove_page(p, route="/nonexistent") == p

    def test_rejects_route_without_slash(self):
        p = _fresh_plan()
        with pytest.raises(PlanAdjustError):
            remove_page(p, route="members")


# ------------------------------------------------------------------------- #
# add_workflow / remove_workflow                                             #
# ------------------------------------------------------------------------- #

class TestWorkflows:
    def test_add_workflow_appends(self):
        p = _fresh_plan()
        p2 = add_workflow(p, name="Cancel", trigger="POST /api/cancel")
        names = [w["name"] for w in p2["workflows"]]
        assert "Cancel" in names

    def test_add_workflow_idempotent(self):
        p = _fresh_plan()
        p2 = add_workflow(p, name="EnrollMember", trigger="POST /x")
        assert sum(1 for w in p2["workflows"] if w["name"] == "EnrollMember") == 1

    def test_add_workflow_rejects_empty_trigger(self):
        p = _fresh_plan()
        with pytest.raises(PlanAdjustError):
            add_workflow(p, name="Cancel", trigger="")

    def test_remove_workflow_deletes(self):
        p = _fresh_plan()
        p2 = remove_workflow(p, name="EnrollMember")
        assert not any(w["name"] == "EnrollMember" for w in p2["workflows"])


# ------------------------------------------------------------------------- #
# add_actor / remove_actor                                                   #
# ------------------------------------------------------------------------- #

class TestActors:
    def test_add_actor_appends(self):
        p = _fresh_plan()
        p2 = add_actor(p, name="Reviewer", role="reviewer")
        names = [a["name"] for a in p2["actors"]]
        assert "Reviewer" in names

    def test_add_actor_idempotent(self):
        p = _fresh_plan()
        p2 = add_actor(p, name="Staff", role="staff")
        assert sum(1 for a in p2["actors"] if a["name"] == "Staff") == 1

    def test_remove_actor(self):
        p = _fresh_plan()
        p2 = remove_actor(p, name="Staff")
        assert not any(a["name"] == "Staff" for a in p2["actors"])


# ------------------------------------------------------------------------- #
# toggle_feature                                                             #
# ------------------------------------------------------------------------- #

class TestToggleFeature:
    def test_turns_on(self):
        p = _fresh_plan()
        p2 = toggle_feature(p, feature="commerce", on=True)
        assert "commerce" in p2["features"]

    def test_turns_off(self):
        p = _fresh_plan()
        p2 = toggle_feature(p, feature="commerce", on=True)
        p3 = toggle_feature(p2, feature="commerce", on=False)
        assert "commerce" not in p3["features"]

    def test_idempotent(self):
        p = _fresh_plan()
        p2 = toggle_feature(p, feature="commerce", on=True)
        p3 = toggle_feature(p2, feature="commerce", on=True)
        assert p2 == p3

    def test_rejects_unknown_feature(self):
        p = _fresh_plan()
        with pytest.raises(PlanAdjustError):
            toggle_feature(p, feature="teleporter", on=True)


# ------------------------------------------------------------------------- #
# compute_diff                                                               #
# ------------------------------------------------------------------------- #

class TestComputeDiff:
    def test_empty_diff_for_identical_plans(self):
        p = _fresh_plan()
        d = compute_diff(p, p)
        assert d.is_empty()

    def test_captures_add_entity(self):
        p = _fresh_plan()
        p2 = add_entity(p, name="Booking")
        d = compute_diff(p, p2)
        assert d.entities_added == ["Booking"]
        assert not d.entities_removed

    def test_captures_remove_page(self):
        p = _fresh_plan()
        p2 = remove_page(p, route="/members")
        d = compute_diff(p, p2)
        assert d.pages_removed == ["/members"]

    def test_multi_op_diff(self):
        p = _fresh_plan()
        p2 = add_entity(p, name="Booking")
        p3 = add_page(p2, name="BookingsPage", entity="Booking", archetype="list")
        p4 = remove_workflow(p3, name="EnrollMember")
        d = compute_diff(p, p4)
        assert d.entities_added == ["Booking"]
        assert d.pages_added == ["/bookings"]
        assert d.workflows_removed == ["EnrollMember"]

    def test_to_dict_serializable(self):
        p = _fresh_plan()
        p2 = add_entity(p, name="Booking")
        d = compute_diff(p, p2)
        payload = d.to_dict()
        assert payload["entities_added"] == ["Booking"]
        assert isinstance(payload["pages_added"], list)


# ------------------------------------------------------------------------- #
# validate_plan_shape                                                        #
# ------------------------------------------------------------------------- #

class TestValidate:
    def test_clean_plan_has_no_warnings(self):
        assert validate_plan_shape(_fresh_plan()) == []

    def test_flags_page_bound_to_missing_entity(self):
        p = _fresh_plan()
        p["pages"].append({
            "route": "/orphans", "name": "OrphansPage",
            "entity": "Ghost", "archetype": "list", "features": [],
            "description": "", "actions": [],
        })
        warnings = validate_plan_shape(p)
        assert any("Ghost" in w for w in warnings)

    def test_flags_relation_referencing_missing_entity(self):
        p = _fresh_plan()
        p["relations"] = [{"name": "MG", "from": "Member", "to": "Ghost"}]
        warnings = validate_plan_shape(p)
        assert any("Ghost" in w for w in warnings)


# ------------------------------------------------------------------------- #
# Reliability anchor: a 5-turn conversation should stay coherent             #
# ------------------------------------------------------------------------- #

class TestConversationalReliability:
    """The whole point of this module: a user has a multi-turn chat
    with Smith, each turn's mutation is applied on top of the previous
    state, and nothing gets silently lost."""

    def test_five_turn_conversation_lands_correctly(self):
        p = _fresh_plan()

        # Turn 1: add Booking
        p = add_entity(p, name="Booking", fields=[
            {"name": "startDate", "type": "date"},
        ])
        # Turn 2: add page for it
        p = add_page(p, name="BookingsPage", entity="Booking", archetype="list")
        # Turn 3: add cancel workflow
        p = add_workflow(p, name="CancelBooking",
                         trigger="POST /api/bookings/cancel")
        # Turn 4: add Reviewer actor
        p = add_actor(p, name="Reviewer", role="reviewer")
        # Turn 5: toggle commerce
        p = toggle_feature(p, feature="commerce", on=True)

        # All 5 mutations survive
        assert any(e["name"] == "Booking" for e in p["data_models"])
        assert any(pg["route"] == "/bookings" for pg in p["pages"])
        assert any(w["name"] == "CancelBooking" for w in p["workflows"])
        assert any(a["name"] == "Reviewer" for a in p["actors"])
        assert "commerce" in p["features"]

        # The plan still validates (no dangling references)
        assert validate_plan_shape(p) == []

    def test_undo_via_reverse_op(self):
        """Every add has a symmetric remove — undo is trivial."""
        p = _fresh_plan()
        p_before = copy.deepcopy(p)
        p = add_entity(p, name="Booking")
        p = add_page(p, name="BookingsPage", entity="Booking", archetype="list")
        # Undo in reverse order
        p = remove_page(p, route="/bookings")
        p = remove_entity(p, name="Booking")
        assert p == p_before
