"""Pages & Nav drew the screens, App Flow drew only the screens a flow
touched, and Smith saw neither picture. The App Map is one: every screen,
the menu, the landings, the links, the flows through each screen, and what
nothing reaches (Mark 8's tax calculator, 2026-10-17)."""
from __future__ import annotations

from services.blueprint.app_map import app_map, describe


def _doc():
    return {
        "roles": [{"id": "ROLE-001", "name": "Owner"}, {"id": "ROLE-002", "name": "Member"}],
        "pages": [
            {"id": "PAGE-001", "name": "Dashboard", "route": "/dashboard", "access": "role_restricted", "users": ["ROLE-001"],
             "entry": True, "navigatesTo": ["PAGE-002"]},
            {"id": "PAGE-002", "name": "Members", "route": "/members", "access": "role_restricted", "users": ["ROLE-001"]},
            {"id": "PAGE-003", "name": "Member", "route": "/members/[id]", "access": "role_restricted", "users": ["ROLE-001"]},
            {"id": "PAGE-004", "name": "Tax", "route": "/tax", "access": "authenticated"},
            {"id": "PAGE-005", "name": "Reports", "route": "/reports", "access": "authenticated"},
            {"id": "PAGE-006", "name": "Old", "route": "/old", "status": "DEPRECATED"},
        ],
        "workflows": [{"id": "WF-001", "name": "Add Member", "launchedFrom": ["PAGE-002"]}],
        "flows": [{"id": "JOURNEY-001", "name": "Add a member", "role": "ROLE-001", "steps": [
            {"page": "PAGE-001", "does": "opens members", "then": "menu"},
            {"page": "PAGE-002", "does": "adds one", "workflow": "WF-001", "then": "go"},
            {"page": "PAGE-003", "does": "sees them"}]}],
        "navigation": {"initialRoute": {"ROLE-001": "/dashboard"},
                       "tree": [{"label": "Home", "page": "PAGE-001"},
                                {"label": "People", "children": [{"label": "Members", "page": "PAGE-002"}]},
                                {"label": "Reports", "page": "PAGE-005"}]},
    }


def test_every_live_screen_is_on_the_map_with_how_people_reach_it():
    m = app_map(_doc())
    by = {s["route"]: s for s in m["screens"]}
    assert list(by) == ["/dashboard", "/members", "/members/[id]", "/tax", "/reports"]
    assert by["/dashboard"]["landing"] == ["Owner"] and by["/dashboard"]["menu"] == "Home"
    assert by["/members"]["menu"] == "Members" and by["/members"]["starts"] == ["Add Member"]
    assert by["/members"]["flows"] == ["Add a member"] and by["/members"]["who"] == ["Owner"]
    assert m["links"] == [{"from": "PAGE-001", "to": "PAGE-002"}]
    assert [n["label"] for n in m["menu"]] == ["Home", "People", "Reports"]
    assert m["menu"][1]["children"][0]["route"] == "/members"


def test_what_nothing_reaches_is_named():
    gaps = {g["page"]: g["kind"] for g in app_map(_doc())["gaps"]}
    assert gaps == {"PAGE-004": "unreachable", "PAGE-005": "no_path"}


def test_smith_reads_the_same_map_in_a_few_lines():
    lines = describe(_doc())
    assert lines[0] == "Lands on after signing in: Owner → /dashboard"
    assert lines[1] == "Menu: Home (/dashboard), People [Members (/members)], Reports (/reports)"
    assert lines[2] == "Links between screens: /dashboard → /members"
    assert any(l.startswith("Gap: Tax (/tax) — nothing leads here") for l in lines)


def test_signing_in_is_never_a_gap():
    doc = _doc()
    doc["pages"].append({"id": "PAGE-009", "name": "Sign in", "route": "/login", "access": "public"})
    assert "PAGE-009" not in {g["page"] for g in app_map(doc)["gaps"]}
