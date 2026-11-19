"""The plan is role by role, and the phone app follows it: the driver's pages are drawn as phone screens, the
administrator's are not. With no plan, every page is drawn, as before."""
from __future__ import annotations

import pytest

from services.blueprint import app_target, platform_plan
from services.blueprint.native_projection import for_phone_roles
from services.blueprint.service import BlueprintService

RIDE = """Ride-hailing.
Driver app:
- Go online or offline, accept or reject ride requests.
- Live location sharing with background GPS, turn-by-turn navigation and push notifications.
Admin dashboard:
- Manage drivers and customers, reports, analytics and payouts."""


def doc_with(native_roles=None):
    doc = {
        "roles": [{"id": "ROLE-1", "name": "Driver"}, {"id": "ROLE-2", "name": "Platform Admin"}, {"id": "ROLE-3", "name": "Rider"}],
        "pages": [
            {"id": "PAGE-1", "route": "/rides/incoming", "access": "role_restricted", "users": ["ROLE-1"]},
            {"id": "PAGE-2", "route": "/admin/drivers", "access": "role_restricted", "users": ["ROLE-2"]},
            {"id": "PAGE-3", "route": "/profile", "access": "authenticated", "users": []},
            {"id": "PAGE-4", "route": "/shared", "access": "role_restricted", "users": ["ROLE-1", "ROLE-2"]},
        ],
        "mobile": {},
    }
    if native_roles is not None:
        doc["mobile"]["nativeRoles"] = native_roles
    return doc


def drawn(doc):
    return [p["id"] for p in doc["pages"] if for_phone_roles(doc, p)]


def test_with_no_plan_every_page_is_drawn_as_before():
    assert drawn(doc_with()) == ["PAGE-1", "PAGE-2", "PAGE-3", "PAGE-4"]
    assert drawn(doc_with([])) == ["PAGE-1", "PAGE-2", "PAGE-3", "PAGE-4"]


def test_a_phone_role_gets_its_pages_and_the_administrators_are_left_out():
    # the driver's page, the page nobody is kept to, and the page the driver shares with the admin
    assert drawn(doc_with(["Driver"])) == ["PAGE-1", "PAGE-3", "PAGE-4"]


def test_a_role_is_matched_by_what_it_is_not_by_the_exact_name():
    # the plan says "Customer"; the app's role is "Rider"; the plan says "Admin"; the app's role is "Platform Admin"
    assert drawn(doc_with(["Admin"])) == ["PAGE-2", "PAGE-3", "PAGE-4"]
    assert "PAGE-1" not in drawn(doc_with(["Customer"]))


def test_a_role_with_both_gets_pages_on_the_phone_too():
    assert drawn(doc_with(["Driver", "Admin"])) == ["PAGE-1", "PAGE-2", "PAGE-3", "PAGE-4"]


def test_the_roles_with_a_phone_come_from_the_settled_plan(tmp_path):
    plan = platform_plan.analyse(RIDE)
    assert plan.needed
    assert platform_plan.native_roles(tmp_path) is None            # nothing settled yet
    platform_plan.write(tmp_path, plan, "accepted")
    assert platform_plan.native_roles(tmp_path) == ["Driver"]       # the admin is web only
    platform_plan.write(tmp_path, plan, "web_only")
    assert platform_plan.native_roles(tmp_path) is None            # the web only: no phone roles


def test_the_blueprint_carries_the_phone_roles_when_it_is_created(tmp_path):
    platform_plan.write(tmp_path, platform_plan.analyse(RIDE), "accepted")
    app_target.write(tmp_path, "web_native")
    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="a", name="Rides", domain="unknown", description=RIDE)
    assert svc.doc["mobile"]["surface"] == "web_native"
    assert svc.doc["mobile"]["nativeRoles"] == ["Driver"]


def test_an_app_with_no_plan_or_no_phone_app_gets_no_phone_roles(tmp_path):
    app_target.write(tmp_path, "web_native")
    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="a", name="A", domain="unknown", description="x")
    assert "nativeRoles" not in svc.doc["mobile"]
    other = tmp_path / "web"
    other.mkdir()
    platform_plan.write(other, platform_plan.analyse(RIDE), "accepted")
    app_target.write(other, "web")                                  # the web only: roles are not recorded
    svc2 = BlueprintService.create(output_dir=str(other), app_id="b", name="B", domain="unknown", description="x")
    assert "nativeRoles" not in svc2.doc["mobile"]
