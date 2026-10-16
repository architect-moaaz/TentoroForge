"""A role with pages only it may open and no `entry` among them used to fail
the page writer outright. FitTrackr (qpqhdugb, 2026-10-16): Receptionist and
Trainer each had their pages and no door, and the build died for a flag the
reply already had the material to set. The first concrete page of theirs is
made the door; a role with no concrete page of its own is still refused."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, RoleWithoutADoor, check_role_doors

DOC = {"roles": [{"id": "ROLE-001", "name": "Gym Owner/Admin"}, {"id": "ROLE-002", "name": "Receptionist"},
                 {"id": "ROLE-003", "name": "Trainer"}, {"id": "ROLE-004", "name": "Member"}],
       "pages": [], "navigation": {}}


def _pages(*bodies):
    return AgentResult(task_id="t", agent="page_design",
                       proposals=[ArtifactProposal(section="pages", natural_key=b["route"], body=b) for b in bodies])


def test_a_role_with_pages_and_no_door_is_given_its_first_concrete_page():
    res = _pages(
        {"name": "Owner Dashboard", "route": "/dashboard", "pattern": "dashboard", "access": "role_restricted", "users": ["ROLE-001"], "entry": True},
        {"name": "Member detail", "route": "/members/[id]", "pattern": "detail", "access": "role_restricted", "users": ["ROLE-002"]},
        {"name": "Attendance Check-in", "route": "/attendance", "pattern": "form", "access": "role_restricted", "users": ["ROLE-002"]},
        {"name": "Members", "route": "/members", "pattern": "list", "access": "role_restricted", "users": ["ROLE-002", "ROLE-001"]},
        {"name": "My Sessions", "route": "/sessions", "pattern": "calendar", "access": "role_restricted", "users": ["ROLE-003"]},
    )
    check_role_doors(res, DOC)
    doors = {b.body["route"]: b.body.get("entry") for b in res.proposals}
    # Receptionist: the list before the form, never the [id] page; Trainer: their one page.
    assert doors["/members"] is True and doors["/sessions"] is True
    assert not doors.get("/attendance") and not doors.get("/members/[id]")
    assert doors["/dashboard"] is True  # the author's own door stands


def test_a_role_whose_only_pages_carry_an_id_is_still_refused():
    with pytest.raises(RoleWithoutADoor) as exc:
        check_role_doors(_pages(
            {"name": "Member detail", "route": "/members/[id]", "pattern": "detail", "access": "role_restricted", "users": ["ROLE-002"]},
        ), DOC)
    assert "Receptionist has pages only Receptionist may open" in str(exc.value)
