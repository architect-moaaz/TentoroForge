"""`/api/read/*` answers an entity or widget only to the people who may open a page that reads it.

The phone's read route took the entity name from the caller and applied ownership rules only, so an entity shown only on
an Admin page was listable by any signed-in Member, and on an app with no sign-in by anyone. The Blueprint says who may
open each page; `read_access` turns that into who may read what, and the route asks it. A column that is not one of the
entity's readable columns is refused wherever a name can be sent."""
from __future__ import annotations

from pathlib import Path

from services.blueprint.app_sdk import emit_schema
from services.blueprint.read_access import read_access

ROUTE = Path(__file__).resolve().parents[2] / "templates/app-foundation/src/app/api/read/[op]/route.ts"


def doc(security=None):
    return {
        "security": {"authentication": "email_password", "signupRole": "ROLE-MEMBER", **(security or {})},
        "roles": [{"id": "ROLE-MEMBER", "name": "Member"}, {"id": "ROLE-ADMIN", "name": "Admin"}],
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Workout", "fields": [{"name": "id"}, {"name": "title"}]},
            {"id": "ENTITY-002", "name": "AuditLog", "fields": [{"name": "id"}, {"name": "action"}]},
            {"id": "ENTITY-003", "name": "Notice", "fields": [{"name": "id"}, {"name": "text"}]},
            {"id": "ENTITY-004", "name": "Orphan", "fields": [{"name": "id"}]},
        ]},
        "pages": [
            {"id": "PAGE-001", "route": "/workouts", "access": "authenticated", "users": ["ROLE-MEMBER"],
             "data": {"primaryEntity": "ENTITY-001"}},
            {"id": "PAGE-002", "route": "/admin/audit", "access": "role_restricted", "users": ["ROLE-ADMIN"],
             "data": {"primaryEntity": "ENTITY-002"}},
            {"id": "PAGE-003", "route": "/news", "access": "public", "data": {"primaryEntity": "ENTITY-003"}},
        ],
        "widgets": [
            {"id": "WIDGET-001", "page": "PAGE-001", "dataSource": {"entity": "ENTITY-001", "op": "query"}},
            {"id": "WIDGET-002", "page": "PAGE-002", "dataSource": {"entity": "ENTITY-002", "op": "query"}},
        ],
    }


def test_a_page_for_any_signed_in_person_opens_its_entity_to_them_and_the_administrator_only():
    a = read_access(doc())["entities"]["Workout"]
    assert a["signedIn"] and not a["anyone"] and "Admin" in a["roles"]


def test_an_entity_on_an_admin_only_page_is_not_a_members():
    a = read_access(doc())["entities"]["AuditLog"]
    assert not a["anyone"] and not a["signedIn"] and a["roles"] == ["Admin"]
    assert "Member" not in a["roles"]


def test_a_public_page_opens_its_entity_to_anyone():
    assert read_access(doc())["entities"]["Notice"]["anyone"]


def test_an_entity_no_page_reads_is_only_the_administrators():
    a = read_access(doc())["entities"]["Orphan"]
    assert not a["anyone"] and not a["signedIn"] and a["roles"] == ["Admin"]


def test_a_widget_is_as_open_as_the_page_it_sits_on():
    w = read_access(doc())["widgets"]
    assert w["WIDGET-001"]["signedIn"] and not w["WIDGET-001"]["anyone"]
    assert w["WIDGET-002"]["roles"] == ["Admin"] and not w["WIDGET-002"]["signedIn"]


def test_an_app_with_no_sign_in_is_open_to_anyone_as_its_pages_are():
    got = read_access(doc({"authentication": "none"}))["entities"]
    assert got["Workout"]["anyone"] and got["AuditLog"]["anyone"]


def test_the_entities_a_page_names_in_its_code_are_read_by_it():
    d = doc()
    d["pages"][0]["data"] = {}
    d["nativeCode"] = [{"page": "PAGE-001", "screen": 'const rows = await list("Workout", {});'}]
    assert read_access(d)["entities"]["Workout"]["signedIn"]


def test_the_generated_schema_carries_the_access_and_the_route_asks_it():
    text = emit_schema(doc())
    assert "export const READ_ACCESS" in text and '"AuditLog"' in text
    route = ROUTE.read_text("utf-8")
    assert "READ_ACCESS.entities[entity]" in route and "READ_ACCESS.widgets[" in route
    assert "unknownColumn(" in route and route.count("unknownColumn(") >= 8, "every place a column name can arrive"
