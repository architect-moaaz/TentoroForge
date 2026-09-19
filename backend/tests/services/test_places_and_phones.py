"""A mobile-first application gets a phone's tab bar, and a place is a distance.

Tool Share asked for "mobile-first" and "browse or search nearby tools" and got
a hamburger drawer and no notion of where anything was. `navigation.mobile`
puts its main destinations in a bottom tab bar; a `location` field holds an
approximate `{lat, lng}` and pages show how far away it is, never where.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.blueprint.account_model import account_fields, project_account
from services.blueprint.app_sdk import ts_type
from services.blueprint.executors import NODE_TASKS
from services.blueprint.page_content import content_brief, content_findings
from services.blueprint.projection import (
    _seed_value, emit_entity_module, mobile_style, mobile_tabs, project_shell,
)
from services.blueprint.ui_engineer import DESIGN_PRINCIPLES, SDK_GUIDE

_BACKEND = Path(__file__).resolve().parents[2]
_APP = _BACKEND / "templates" / "app-foundation"
_SHELL = _APP / "src" / "app" / "(dashboard)"

MEMBER, TOOL = "ENTITY-001", "ENTITY-003"


# --------------------------------------------------------------- tab bar

def _pages(n_phone: int, n_other: int) -> list[dict]:
    return ([{"id": f"P{i}", "route": f"/p{i}", "responsive": {"mobile": "primary"}} for i in range(n_phone)]
            + [{"id": f"Q{i}", "route": f"/q{i}", "responsive": {"mobile": "supported"}} for i in range(n_other)])


def test_a_phone_first_product_gets_tabs_unless_the_blueprint_says_otherwise():
    assert mobile_style({"pages": _pages(3, 1)}) == "tabs"
    assert mobile_style({"pages": _pages(1, 3)}) == "drawer"
    assert mobile_style({"pages": _pages(1, 3), "navigation": {"mobile": "tabs"}}) == "tabs"
    assert mobile_style({"pages": _pages(3, 1), "navigation": {"mobile": "drawer"}}) == "drawer"


def test_the_tabs_are_the_first_main_destinations(tmp_path):
    groups = [{"label": "Discover", "route": "/tools", "icon": "search"},
              {"label": "Rentals", "items": [{"label": "My rentals", "route": "/rentals"},
                                             {"label": "History", "route": "/history"}]},
              {"label": "A", "route": "/a"}, {"label": "B", "route": "/b"},
              {"label": "C", "route": "/c"}, {"label": "D", "route": "/d"}]
    tabs = mobile_tabs({"navigation": {"mobile": "tabs"}}, groups)
    assert [t["route"] for t in tabs] == ["/tools", "/rentals", "/a", "/b", "/c"]
    assert tabs[0]["icon"] == "search"
    assert mobile_tabs({"navigation": {"mobile": "drawer"}}, groups) == []

    doc = {"application": {"name": "T"}, "pages": [{"id": "P1", "route": "/tools"}, {"id": "P2", "route": "/rentals"}],
           "navigation": {"mobile": "tabs", "tree": [{"label": "Discover", "page": "P1"}, {"label": "Rentals", "page": "P2"}]}}
    project_shell(doc, tmp_path)
    shell = json.loads((tmp_path / "src/schemas/shell.json").read_text())
    assert shell["mobile"] == {"style": "tabs", "tabs": [{"label": "Discover", "route": "/tools"},
                                                         {"label": "Rentals", "route": "/rentals"}]}


def test_every_shell_renders_the_bar_on_a_phone_and_the_dock_steps_aside():
    layout = (_SHELL / "layout.tsx").read_text()
    body = layout[layout.index("const body = ("):layout.index("const appName")]
    assert "<MobileTabBar" in body and 'className="h-20 md:hidden"' in body
    assert 'mobileTabs.length ? "hidden md:block"' in layout
    bar = (_SHELL / "MobileTabBar.tsx").read_text()
    assert "md:hidden" in bar and "safe-area-inset-bottom" in bar and 'aria-current={on ? "page"' in bar
    assert "HOW A PHONE GETS AROUND" in NODE_TASKS["ux_architecture"]


# --------------------------------------------------------------- places

def test_a_location_is_one_jsonb_column_typed_as_a_point(tmp_path):
    tool = {"id": TOOL, "name": "Tool", "table": "tools", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True}, {"name": "pickup", "type": "location"}]}
    module = emit_entity_module(tool, {"data": {"entities": [tool]}})
    assert 'pickup: jsonb("pickup")' in module
    assert ts_type({"type": "location"}) == "{ lat: number; lng: number }"
    assert _seed_value({"name": "pickup", "type": "location"}, "Tool", 2) is None, "no invented place"


def test_signup_does_not_ask_for_a_location_but_the_sdk_knows_where_home_is(tmp_path):
    doc = {"data": {"entities": [{"id": MEMBER, "name": "Member", "table": "members", "account": True, "fields": [
        {"name": "id", "type": "uuid"}, {"name": "fullName", "type": "string", "required": True},
        {"name": "home", "type": "location"}]}]}}
    assert [f["name"] for f in account_fields(doc)] == ["fullName"]
    project_account(doc, tmp_path)
    assert '"locationField": "home"' in (tmp_path / "src/lib/account.ts").read_text()


def _doc():
    return {"data": {"entities": [
        {"id": MEMBER, "name": "Member", "table": "members", "fields": [
            {"name": "id", "type": "uuid"}, {"name": "home", "type": "location"}, {"name": "bio", "type": "text"}]},
        {"id": TOOL, "name": "Tool", "table": "tools", "fields": [
            {"name": "id", "type": "uuid"}, {"name": "ownerId", "type": "uuid", "references": MEMBER}]},
    ]}}


def _page(*content, route="/tools/[id]"):
    return {"id": "P", "route": route, "data": {"primaryEntity": TOOL}, "content": list(content)}


def test_a_distance_fact_resolves_to_a_location():
    near_owner = {"label": "Distance", "source": {"kind": "distance", "via": "ownerId", "entity": MEMBER, "field": "home"}}
    assert content_findings(_page(near_owner), _doc()) == []
    wrong = {"label": "Distance", "source": {"kind": "distance", "via": "ownerId", "entity": MEMBER, "field": "bio"}}
    assert "not a `location`" in content_findings(_page(wrong), _doc())[0]
    missing = {"label": "Distance", "source": {"kind": "distance", "field": "pickup"}}
    assert "type `location`" in content_findings(_page(missing), _doc())[0]
    proposed = {"label": "Distance", "source": {"kind": "distance", "field": "pickup", "newField": {"type": "location"}}}
    assert content_findings(_page(proposed), _doc()) == []
    read = content_brief(_doc(), _page(near_owner))[0]["read"]
    assert read == 'formatDistance(distanceKm(await whereAmI(ctx), (await record("Member", tool.ownerId))?.home))'


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_shipped_geo_helpers_measure_and_say_it_like_a_person(tmp_path):
    script = tmp_path / "probe.mts"
    script.write_text(
        f'import {{ distanceKm, formatDistance, parseNear, roundPoint }} from "{(_APP / "src/sdk/geo.ts").as_posix()}";\n'
        "const km = distanceKm({ lat: 51.507, lng: -0.128 }, { lat: 51.513, lng: -0.128 });\n"
        "console.log(JSON.stringify({ km: Math.round(km * 1000), mi: formatDistance(km, 'en-GB'),\n"
        "  metric: formatDistance(km, 'de-DE'), far: formatDistance(25, 'fr-FR'), none: formatDistance(null),\n"
        "  near: parseNear('51.5,-0.12'), bad: parseNear('nowhere'), round: roundPoint({ lat: 51.50749, lng: -0.12761 }) }));\n")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["km"] == 667 and got["mi"] == "0.4 mi" and got["metric"] == "700 m" and got["far"] == "25 km"
    assert got["none"] == "" and got["near"] == {"lat": 51.5, "lng": -0.12} and got["bad"] is None
    assert got["round"] == {"lat": 51.507, "lng": -0.128}


def test_the_sdk_the_editor_and_the_prompts_carry_places():
    server = (_APP / "src/sdk/server.ts").read_text()
    client = (_APP / "src/sdk/client.tsx").read_text()
    assert "export async function near<" in server and "export async function whereAmI(" in server
    assert "export function NearMe(" in client and 'kind === "location"' in client
    assert 'kind: "location"' in client, "a GeoPoint input takes the location field"
    samples = (_BACKEND / "static/jit-samples.mjs").read_text()
    assert "export async function near(" in samples and "export async function whereAmI(" in samples
    assert "`location`" in NODE_TASKS["entity_fields"] and "`distance`" in NODE_TASKS["page_details"]
    assert "PLACES ARE DISTANCES" in DESIGN_PRINCIPLES and "whereAmI(ctx)" in SDK_GUIDE


def test_the_architect_chooses_the_tabs_and_their_icons():
    groups = [{"label": "Home", "route": "/"}, {"label": "Find", "route": "/find", "icon": "map-pin", "tab": True},
              {"label": "Work", "items": [{"label": "Jobs", "route": "/jobs", "icon": "hammer", "tab": True},
                                          {"label": "Quotes", "route": "/quotes"}]},
              {"label": "Me", "route": "/me", "tab": True}]
    tabs = mobile_tabs({"navigation": {"mobile": "tabs"}}, groups)
    assert tabs == [{"label": "Find", "route": "/find", "icon": "map-pin"},
                    {"label": "Jobs", "route": "/jobs", "icon": "hammer"},
                    {"label": "Me", "route": "/me"}]
    assert "`tab: true`" in NODE_TASKS["ux_architecture"] and "`icon`" in NODE_TASKS["ux_architecture"]
    layout = (_SHELL / "layout.tsx").read_text()
    assert "lucideByName(key)" in layout, "any lucide icon the architect names renders"


def test_a_view_of_a_page_is_its_own_destination(tmp_path):
    """0l133sp2: "My Listings" pointed at /tools like "Discover" — both lit,
    and the tab bar drew two children keyed `/tools`."""
    doc = {"application": {"name": "T"}, "pages": [{"id": "P1", "route": "/tools"}],
           "navigation": {"mobile": "tabs", "tree": [
               {"label": "Discover", "page": "P1", "tab": True},
               {"label": "My Listings", "page": "P1", "view": "mine", "tab": True},
               {"label": "Again", "page": "P1", "tab": True}]}}
    project_shell(doc, tmp_path)
    shell = json.loads((tmp_path / "src/schemas/shell.json").read_text())
    rail = shell["children"][0]["props"]
    assert [g["route"] for g in rail["groups"]] == ["/tools", "/tools?view=mine", "/tools"]
    assert [t["route"] for t in shell["mobile"]["tabs"]] == ["/tools", "/tools?view=mine"], "one tab per address"
    assert rail["bg"] == "hsl(var(--inverse))" and rail["accent"] == "hsl(var(--accent))", "painted from the design"
    bar = (_SHELL / "MobileTabBar.tsx").read_text()
    assert "key={`${t.route}:${t.label}`}" in bar
    layout = (_SHELL / "layout.tsx").read_text()
    assert "glyph: <RailGlyph name={g.icon} size={20} />" in layout and "<React.Suspense" in layout
    side = (_BACKEND.parent / "packages/library/src/components/SideNav/SideNav.tsx").read_text()
    assert "item.glyph ??" in side and "routes.includes(active)" in side
