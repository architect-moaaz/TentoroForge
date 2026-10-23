"""The native project: the fixed half, the generated half, one screen per page.

`<output_dir>/native/` is the template with this application's name, bundle id
and brand colour, the typed modules the web's own SDK emits, the design tokens
and config, and a screen with its route for every `nativeCode` row. It is
written only when the application asks for a native app, and a page that goes
takes its screen with it."""
from __future__ import annotations

import json

from services.blueprint.native_projection import (
    NATIVE_DIR, bundle_id, drawn_pages, enabled, native_root, project_native, route_file,
)

SCREEN = "export default function Screen() { return null; }"

DOC = {
    "application": {"name": "Field Crew"},
    "product": {"locale": "en-GB", "languages": ["en-GB", "ar"]},
    "mobile": {"native": {"enabled": True}, "store": {"bundleId": "com.acme.fieldcrew"}},
    "designSystem": {"colors": {"primary": "hsl(243 75% 59%)"}},
    "roles": [{"id": "ROLE-001", "name": "Worker"}],
    "security": {},
    "data": {"entities": [{"id": "ENTITY-001", "name": "Job", "fields": [
        {"name": "title", "type": "text"}, {"name": "price", "type": "money"}]}]},
    "workflows": [],
    "pages": [
        {"id": "PAGE-001", "name": "Home", "route": "/", "access": "authenticated"},
        {"id": "PAGE-002", "name": "Job", "route": "/jobs/[id]", "access": "authenticated"},
        {"id": "PAGE-003", "name": "Sign in", "route": "/login", "pattern": "auth", "access": "public"},
        {"id": "PAGE-004", "name": "Org", "route": "/organisation", "access": "authenticated"},
    ],
    "nativeCode": [
        {"page": "PAGE-001", "screen": SCREEN, "parts": {"list": "export const List = 1;"}},
        {"page": "PAGE-002", "screen": SCREEN},
        {"page": "PAGE-004", "screen": SCREEN},
    ],
}


def test_only_an_application_that_asks_gets_a_native_project(tmp_path):
    off = {**DOC, "mobile": {}}
    assert not enabled(off)
    assert project_native(off, tmp_path) == {"files": [], "enabled": False}
    assert not (tmp_path / NATIVE_DIR).exists()


def test_the_fixed_half_carries_this_application(tmp_path):
    project_native(DOC, tmp_path)
    root = native_root(tmp_path)
    text = (root / "app.json").read_text("utf-8")
    app = json.loads(text)["expo"]
    assert app["name"] == "Field Crew" and app["slug"] == "field-crew"
    assert app["ios"]["bundleIdentifier"] == "com.acme.fieldcrew" == app["android"]["package"]
    assert "__APP_" not in text and "__BUNDLE_ID__" not in text, "no placeholder survived"
    assert "__APP_NAME__" not in (root / "package.json").read_text("utf-8")
    for fixed in ("app/_layout.tsx", "app/login.tsx", "src/sdk/index.ts", "src/ui/index.ts", "src/theme.ts", "eas.json"):
        assert (root / fixed).is_file(), fixed
    # What the template keeps for itself is not shipped.
    assert not (root / "_placeholders").exists() and not (root / "__tests__").exists()
    assert (root / "assets" / "icon.png").is_file() and (root / "assets" / "splash.png").is_file()


def test_the_bundle_id_is_the_owners_else_made_from_the_name():
    assert bundle_id(DOC) == "com.acme.fieldcrew"
    assert bundle_id({"application": {"name": "Field Crew"}}) == "com.tentoro.fieldcrew"


def test_the_typed_modules_are_the_webs_own(tmp_path):
    from services.blueprint.app_sdk import emit_pages, emit_schema, emit_widgets, emit_workflows
    project_native(DOC, tmp_path)
    sdk = native_root(tmp_path) / "src" / "sdk"
    assert (sdk / "schema.ts").read_text("utf-8") == emit_schema(DOC)
    assert (sdk / "workflows.ts").read_text("utf-8") == emit_workflows(DOC)
    assert (sdk / "pages.ts").read_text("utf-8") == emit_pages(DOC)
    assert (sdk / "widgets.ts").read_text("utf-8") == emit_widgets(DOC)
    assert "interface Job" in (sdk / "schema.ts").read_text("utf-8")


def test_the_config_and_theme_say_what_the_blueprint_says(tmp_path):
    project_native(DOC, tmp_path)
    cfg = (native_root(tmp_path) / "src" / "config.generated.ts").read_text("utf-8")
    assert 'APP_NAME: string = "Field Crew"' in cfg and 'LOCALE: string = "en-GB"' in cfg
    assert '"tag": "ar"' in cfg and '"dir": "rtl"' in cfg
    assert 'CURRENCY: string = "GBP"' in cfg
    theme = (native_root(tmp_path) / "src" / "theme.generated.ts").read_text("utf-8")
    assert "export const colors" in theme and "export const radius" in theme


def test_a_screen_and_its_route_for_each_page(tmp_path):
    out = project_native(DOC, tmp_path)
    root = native_root(tmp_path)
    assert (root / "src/screens/PAGE-001.tsx").is_file() and (root / "src/screens/PAGE-001/list.tsx").is_file()
    assert (root / "app/index.tsx").read_text("utf-8") == 'export { default } from "@/screens/PAGE-001";\n'
    assert (root / "app/jobs/[id].tsx").read_text("utf-8") == 'export { default } from "@/screens/PAGE-002";\n'
    assert "src/screens/PAGE-002.tsx" in out["files"]


def test_the_fixed_routes_are_never_overwritten_by_another_page(tmp_path):
    project_native(DOC, tmp_path)
    root = native_root(tmp_path)
    # the sign-in page is a native page now (a frame around the kit's form), but DOC gives it no screen yet:
    assert [p["id"] for p in drawn_pages(DOC)] == ["PAGE-001", "PAGE-002", "PAGE-003", "PAGE-004"]
    assert not (root / "src/screens/PAGE-003.tsx").exists()
    assert "SignInForm" in (root / "app/login.tsx").read_text("utf-8"), "the fallback is in place"
    # PAGE-004's route is the fixed organisation screen: its screen is written, the fixed route stays.
    assert route_file("/organisation") is None and route_file("/login") is None
    assert "@/screens/PAGE-004" not in (root / "app/organisation.tsx").read_text("utf-8")


def test_a_page_that_goes_takes_its_screen_and_its_route(tmp_path):
    project_native(DOC, tmp_path)
    root = native_root(tmp_path)
    gone = {**DOC, "pages": [p for p in DOC["pages"] if p["id"] != "PAGE-002"]}
    out = project_native(gone, tmp_path)
    assert not (root / "src/screens/PAGE-002.tsx").exists() and not (root / "app/jobs/[id].tsx").exists()
    assert "-src/screens/PAGE-002.tsx" in out["files"]
    assert (root / "src/screens/PAGE-001.tsx").is_file()


def test_projecting_twice_writes_nothing_the_second_time(tmp_path):
    project_native(DOC, tmp_path)
    assert project_native(DOC, tmp_path)["files"] == []


def test_an_eas_project_id_is_kept(tmp_path):
    project_native(DOC, tmp_path)
    app_json = native_root(tmp_path) / "app.json"
    data = json.loads(app_json.read_text("utf-8"))
    data["expo"]["extra"]["eas"]["projectId"] = "abc-123"
    app_json.write_text(json.dumps(data, indent=2), "utf-8")
    project_native(DOC, tmp_path)
    assert json.loads(app_json.read_text("utf-8"))["expo"]["extra"]["eas"]["projectId"] == "abc-123"


# --- the bottom tabs: the main pages ------------------------------------------------------------

TABBED = {
    **DOC,
    "navigation": {"tree": [{"label": "Jobs", "icon": "Wrench", "page": "PAGE-001"},
                            {"label": "Add Job", "icon": "PlusCircle", "page": "PAGE-002"},
                            {"label": "Crew Board", "icon": "BarChart3", "page": "PAGE-004"}]},
    "pages": [{**p, "pattern": {"PAGE-001": "entity_list", "PAGE-002": "form", "PAGE-004": "dashboard"}.get(p["id"], p.get("pattern")),
               "route": {"PAGE-001": "/jobs", "PAGE-004": "/board"}.get(p["id"], p["route"])}
              for p in DOC["pages"]],
    "nativeCode": [{**r, "page": r["page"]} for r in DOC["nativeCode"]],
}


def test_the_main_pages_are_the_tabs_and_not_a_form_or_a_record():
    from services.blueprint.native_projection import is_tab, tab_pages
    assert [p["id"] for p in tab_pages(TABBED)] == ["PAGE-001", "PAGE-004"]
    assert is_tab(TABBED, "PAGE-001") and not is_tab(TABBED, "PAGE-002") and not is_tab(TABBED, "PAGE-003")


def test_one_main_page_or_none_is_no_tab_bar():
    from services.blueprint.native_projection import tab_pages
    assert tab_pages(DOC) == [], "no navigation: nothing to show"
    open_app = {**TABBED, "security": {"authentication": "none"}}
    one = {**open_app, "navigation": {"tree": [{"label": "Jobs", "page": "PAGE-001"}]}}
    assert tab_pages(one) == [], "a lone page of an app with no sign-in needs no bar"
    signed_in = {**TABBED, "navigation": {"tree": [{"label": "Jobs", "page": "PAGE-001"}]}}
    assert [p["id"] for p in tab_pages(signed_in)] == ["PAGE-001"], "…but with a sign-in the account tab makes it a bar"


def test_a_tab_bar_is_written_with_its_screens_in_the_tabs_group(tmp_path):
    out = project_native(TABBED, tmp_path)
    root = native_root(tmp_path)
    nav = (root / "src" / "navigation.generated.ts").read_text("utf-8")
    assert '"name": "jobs"' in nav and '"icon": "construct"' in nav and '"icon": "stats-chart"' in nav
    assert (root / "app/(tabs)/_layout.tsx").is_file()
    assert (root / "app/(tabs)/index.tsx").exists() is False
    assert (root / "app/(tabs)/jobs.tsx").read_text("utf-8") == 'export { default } from "@/screens/PAGE-001";\n'
    # A form and a record are stacked above the tabs, at their own addresses.
    assert (root / "app/jobs/[id].tsx").is_file() and not (root / "app/(tabs)/jobs/[id].tsx").exists()
    assert "app/(tabs)/_layout.tsx" in out["files"]


def test_an_app_without_tabs_has_no_tab_layout(tmp_path):
    project_native(DOC, tmp_path)
    assert not (native_root(tmp_path) / "app" / "(tabs)").exists()
    assert "export const TABS" in (native_root(tmp_path) / "src" / "navigation.generated.ts").read_text("utf-8")


def test_going_from_tabs_to_none_takes_the_tab_files_with_it(tmp_path):
    project_native(TABBED, tmp_path)
    root = native_root(tmp_path)
    project_native({**TABBED, "navigation": {"tree": []}}, tmp_path)
    assert not (root / "app/(tabs)/jobs.tsx").exists() and not (root / "app/(tabs)/_layout.tsx").exists()
    assert (root / "app/jobs.tsx").exists(), "…and the page is a plain route again"


def test_the_root_forwards_to_home_when_no_page_is_at_the_root(tmp_path):
    project_native({**DOC, "pages": [dict(p, route=p["route"] if p["route"] != "/" else "/home") for p in DOC["pages"]]}, tmp_path)
    root = native_root(tmp_path)
    src = (root / "app" / "index.tsx").read_text("utf-8")
    assert "Redirect" in src and "HOME" in src


def test_a_page_at_the_root_is_the_root_and_nothing_forwards(tmp_path):
    project_native(DOC, tmp_path)
    assert (native_root(tmp_path) / "app/index.tsx").read_text("utf-8") == 'export { default } from "@/screens/PAGE-001";\n'


# --- an app with a sign-in has a way to make an account, and a way out ----------------------------

SIGNUP_PAGES = [{"id": "PAGE-005", "name": "Sign Up", "route": "/signup", "pattern": "auth", "access": "public"},
                {"id": "PAGE-006", "name": "Sign In", "route": "/login", "pattern": "auth", "access": "public"}]


def test_the_phone_can_create_an_account_when_the_app_has_a_sign_up_and_passwords():
    from services.blueprint.native_projection import can_sign_up
    assert can_sign_up({**DOC, "pages": DOC["pages"] + SIGNUP_PAGES}) is True
    assert can_sign_up({**DOC, "pages": SIGNUP_PAGES[1:]}) is True, "the sign-up page is added to every plan with a sign-in, so the phone shows its link"
    no_passwords = {**DOC, "pages": DOC["pages"] + SIGNUP_PAGES, "security": {"signIn": {"password": False, "magicLink": True}}}
    assert can_sign_up(no_passwords) is False, "the phone signs in with a password; an email link needs a browser"


def test_the_config_says_whether_an_account_can_be_made_and_where_it_goes(tmp_path):
    project_native({**DOC, "pages": DOC["pages"] + SIGNUP_PAGES}, tmp_path)
    cfg = (native_root(tmp_path) / "src" / "config.generated.ts").read_text("utf-8")
    assert "CAN_SIGN_UP: boolean = true" in cfg and 'AFTER_SIGNUP: string = "' in cfg


def test_an_app_with_a_sign_in_ends_its_tab_bar_with_the_account_tab(tmp_path):
    project_native(TABBED, tmp_path)
    root = native_root(tmp_path)
    nav = (root / "src" / "navigation.generated.ts").read_text("utf-8")
    assert nav.index('"name": "board"') < nav.index('"name": "account"'), "the account tab is the last"
    assert '"icon": "person-circle-outline"' in nav
    assert "Sign out" in (root / "app/(tabs)/account.tsx").read_text("utf-8")


def test_an_app_with_no_sign_in_has_no_account_tab(tmp_path):
    project_native({**TABBED, "security": {"authentication": "none"}}, tmp_path)
    root = native_root(tmp_path)
    assert (root / "app/(tabs)/_layout.tsx").is_file() and not (root / "app/(tabs)/account.tsx").exists()
    assert '"name": "account"' not in (root / "src" / "navigation.generated.ts").read_text("utf-8")


def test_a_page_of_the_apps_own_at_account_is_not_shadowed(tmp_path):
    mine = {**TABBED, "pages": [dict(p, route="/account") if p["id"] == "PAGE-004" else p for p in TABBED["pages"]]}
    project_native(mine, tmp_path)
    assert not (native_root(tmp_path) / "app/(tabs)/account.tsx").exists() or \
        'export { default } from "@/screens/PAGE-004"' in (native_root(tmp_path) / "app/(tabs)/account.tsx").read_text("utf-8")


def test_a_page_at_the_fixed_signup_route_is_never_drawn_over_it():
    from services.blueprint.native_projection import route_file
    assert route_file("/signup") is None and route_file("/login") is None


# --- an application with nothing to sign in to has no sign-in (FocusFlow, 2026-10-22) ----------------------------

OPEN_APP = {"application": {"name": "FocusFlow"}, "security": {"authentication": "email_password", "rbac": False, "protectedRoutes": [],
                                                           "signIn": {"magicLink": False, "password": True, "sso": []}},
            "pages": [{"id": "PAGE-001", "name": "Focus", "route": "/", "access": "public"},
                      {"id": "PAGE-002", "name": "History", "route": "/history", "access": "public"}],
            "data": {"entities": [{"name": "FocusSession"}]}}


def test_an_application_whose_pages_are_all_public_and_has_no_users_has_no_sign_in():
    from services.blueprint.account_model import auth_page_bodies, has_sign_in
    from services.blueprint.native_projection import can_sign_up, has_account_tab
    assert has_sign_in(OPEN_APP) is False
    assert auth_page_bodies(OPEN_APP) == []
    assert has_account_tab(OPEN_APP) is False and can_sign_up(OPEN_APP) is False


def test_one_page_that_needs_a_login_brings_the_sign_in_back():
    from services.blueprint.account_model import has_sign_in
    from services.blueprint.native_projection import can_sign_up, has_account_tab
    guarded = {**OPEN_APP, "pages": OPEN_APP["pages"] + [{"id": "PAGE-003", "name": "Settings", "route": "/settings", "access": "authenticated"}]}
    assert has_sign_in(guarded) and has_account_tab(guarded) and can_sign_up(guarded)
    with_roles = {**OPEN_APP, "roles": [{"id": "ROLE-001", "name": "Admin"}]}
    assert has_sign_in(with_roles)
    with_account = {**OPEN_APP, "data": {"entities": [{"name": "Member", "account": True}]}}
    assert has_sign_in(with_account)
    with_link = {**OPEN_APP, "security": {**OPEN_APP["security"], "signIn": {"magicLink": True, "password": False}}}
    assert has_sign_in(with_link)


def test_a_plan_with_a_sign_in_but_no_sign_up_page_yet_still_lets_the_phone_create_an_account():
    from services.blueprint.native_projection import can_sign_up
    plan = {**OPEN_APP, "roles": [{"id": "ROLE-001", "name": "Member"}]}
    assert can_sign_up(plan) is True
