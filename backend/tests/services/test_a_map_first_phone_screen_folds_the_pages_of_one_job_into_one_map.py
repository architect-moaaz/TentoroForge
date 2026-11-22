"""A person out and moving gets ONE map screen on the phone, whose sheet changes with the job, instead of a page each for the
home, the offer and the trip. The web keeps every page. Found by comparing Forge's driver app with how every ride-hailing
app is built: Forge translated each web page into a phone screen, so the map sat in a card on a page of cards."""
from __future__ import annotations

from services.blueprint import map_first, platform_plan
from services.blueprint import native_engineer, native_projection as np_
from services.blueprint.app_target import apply
from services.blueprint.functional_completeness import functional_findings

RIDE = """Ride-hailing.
Driver app:
- Go online or offline, accept or reject ride requests.
- Live location sharing with background GPS, turn-by-turn navigation and push notifications.
- Earnings and ride history.
Admin dashboard:
- Manage drivers and customers, reports, analytics and payouts."""


def doc(**over):
    d = {
        "application": {"name": "Rides"},
        "roles": [{"id": "ROLE-1", "name": "Driver"}, {"id": "ROLE-2", "name": "Admin"}],
        "pages": [
            {"id": "PAGE-001", "name": "Driver Home", "route": "/", "pattern": "dashboard", "access": "role_restricted", "users": ["ROLE-1"],
             "purpose": "Where a driver goes online.", "phone": {"experience": "map_first", "covers": ["PAGE-004", "PAGE-005", "PAGE-006"]}},
            {"id": "PAGE-004", "name": "Live Position", "route": "/live-map", "pattern": "command_center", "access": "role_restricted", "users": ["ROLE-1"], "purpose": "Own position."},
            {"id": "PAGE-005", "name": "Incoming Ride Request", "route": "/rides/incoming", "pattern": "approval_inbox", "access": "role_restricted", "users": ["ROLE-1"], "purpose": "An offered ride."},
            {"id": "PAGE-006", "name": "Active Trip", "route": "/rides/active", "pattern": "record_workspace", "access": "role_restricted", "users": ["ROLE-1"], "purpose": "The current ride."},
            {"id": "PAGE-007", "name": "Earnings", "route": "/earnings", "pattern": "analytics", "access": "role_restricted", "users": ["ROLE-1"]},
            {"id": "PAGE-011", "name": "Overview", "route": "/admin", "pattern": "dashboard", "access": "role_restricted", "users": ["ROLE-2"]},
        ],
        "workflows": [
            {"id": "FLOW-004", "name": "Accept ride", "launchedFrom": ["PAGE-005"], "steps": []},
            {"id": "FLOW-006", "name": "Mark arrived", "launchedFrom": ["PAGE-006"], "steps": []},
            {"id": "FLOW-002", "name": "Go online", "launchedFrom": ["PAGE-001"], "steps": []},
        ],
        "navigation": {"mobile": "tabs", "tree": [{"label": "Home", "page": "PAGE-001"}, {"label": "Offers", "page": "PAGE-005"},
                                                   {"label": "Trip", "page": "PAGE-006"}, {"label": "Earnings", "page": "PAGE-007"}]},
        "mobile": {"native": {"enabled": True}, "surface": "web_native", "nativeRoles": ["Driver"]},
    }
    d.update(over)
    return d


def test_the_plan_marks_a_role_that_moves_as_map_first_and_a_desk_role_as_not():
    plan = platform_plan.analyse(RIDE)
    roles = {r.role: r.experience for r in plan.roles}
    assert roles["Driver"] == "map_first"
    assert roles["Admin"] == "screens"
    assert "built around the map" in platform_plan.question(plan)


def test_the_settled_plan_reaches_the_blueprint(tmp_path):
    platform_plan.write(tmp_path, platform_plan.analyse(RIDE), "accepted")
    assert platform_plan.map_first_roles(tmp_path) == ["Driver"]
    out = apply({"application": {"name": "Rides"}}, "web_native", ["Driver"], platform_plan.map_first_roles(tmp_path))
    assert out["mobile"]["mapFirstRoles"] == ["Driver"]
    web = apply({"application": {"name": "Rides"}}, "web", ["Driver"], ["Driver"])
    assert "mapFirstRoles" not in web["mobile"]          # a website-only app has no phone roles at all


def test_a_covered_page_is_a_state_of_the_map_screen_not_a_screen_or_a_tab():
    d = doc()
    assert map_first.covered_by(d) == {"PAGE-004": "PAGE-001", "PAGE-005": "PAGE-001", "PAGE-006": "PAGE-001"}
    drawn = [p["id"] for p in np_.drawn_pages(d)]
    assert "PAGE-001" in drawn and "PAGE-007" in drawn
    assert not {"PAGE-004", "PAGE-005", "PAGE-006"} & set(drawn)
    assert [p["id"] for p in np_.main_pages(d)] == ["PAGE-001", "PAGE-007"]


def test_without_the_setting_every_page_is_its_own_screen_as_before():
    d = doc()
    d["pages"][0].pop("phone")
    assert map_first.covered_by(d) == {}
    assert {"PAGE-004", "PAGE-005", "PAGE-006"} <= {p["id"] for p in np_.drawn_pages(d)}


def test_the_native_builder_is_told_what_the_map_screen_folds_in():
    d = doc()
    page = d["pages"][0]
    prompt = native_engineer.user_prompt(d, page)
    assert "MAP-FIRST HOME" in prompt and "Incoming Ride Request" in prompt and "Active Trip" in prompt
    assert "workflows.acceptRide" in prompt and "workflows.markArrived" in prompt   # the folded pages' controls are the screen's
    assert "state machine over the DATA" in prompt and "never over local flags" in prompt
    assert "web page as it is written now" not in prompt                            # the web's layout is not the model for it
    assert "A map-first screen" in native_engineer.system_prompt(d)
    plain = doc(); plain["pages"][0].pop("phone")
    assert "A map-first screen" not in native_engineer.system_prompt(plain)


def test_a_map_screen_must_run_the_workflows_of_the_pages_it_covers_and_need_not_link_to_them():
    d = doc()
    page = d["pages"][0]
    bare = "export default function Screen() { return null; }"
    problems = native_engineer._page_findings(d, page, bare)
    text = " ".join(problems)
    assert "Accept ride" in text and "Mark arrived" in text and "Go online" in text      # every control must exist in some state
    wired = "workflows.acceptRide workflows.markArrived workflows.goOnline"
    assert not [p for p in native_engineer._page_findings(d, page, wired) if "launched from this page" in p]


def test_the_blueprint_refuses_a_map_screen_it_cannot_honour():
    d = doc()
    d["pages"][0]["phone"]["covers"] = ["PAGE-004", "PAGE-404", "PAGE-001", "PAGE-011"]
    rules = {f["rule"] for f in map_first.findings(d)}
    assert {"map-screen-covers-no-page", "map-screen-covers-a-map-screen", "map-screen-hides-a-page-from-its-people"} <= rules
    assert "map-screen-covers-no-page" in {f["rule"] for f in functional_findings(d)}
    e = doc(); e["mobile"]["mapFirstRoles"] = ["Driver"]; e["pages"][0].pop("phone")
    assert "map-first-role-without-a-map-screen" in {f["rule"] for f in map_first.findings(e)}
    assert map_first.findings(doc()) == []


def test_the_page_agent_is_told_when_to_give_a_role_a_map_home():
    from pathlib import Path
    from services.blueprint import executors
    text = Path(executors.__file__).read_text(encoding="utf-8")
    assert "A PERSON WHO WORKS FROM THE ROAD GETS A MAP-FIRST HOME ON THE PHONE" in text and "mobile.mapFirstRoles" in text


def test_a_tab_whose_page_sits_in_a_folder_is_named_by_its_whole_path():
    # found on the emulator: the tab was named "history" but its file is rides/history, so the bar showed the raw path
    d = doc()
    d["pages"].append({"id": "PAGE-008", "name": "Ride History", "route": "/rides/history", "pattern": "entity_list",
                       "access": "role_restricted", "users": ["ROLE-1"]})
    d["navigation"]["tree"].append({"label": "History", "page": "PAGE-008"})
    module = np_.navigation_module(d)
    assert '"name": "rides/history"' in module and '"name": "earnings"' in module and '"name": "index"' in module


def test_the_map_zooms_in_on_the_person_the_first_time_and_the_brief_keeps_the_tab_bar_to_itself():
    from pathlib import Path
    smap = (Path(__file__).resolve().parents[2] / "templates" / "native" / "src" / "sdk" / "map.tsx").read_text(encoding="utf-8")
    assert "followedOnce" in smap and "zoom: 16" in smap
    brief = map_first.brief(doc(), doc()["pages"][0])
    assert "do NOT repeat them as floating buttons" in brief
