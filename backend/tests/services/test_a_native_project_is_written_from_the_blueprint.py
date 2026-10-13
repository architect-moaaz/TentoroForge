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


def test_the_sign_in_and_the_fixed_routes_are_never_drawn(tmp_path):
    project_native(DOC, tmp_path)
    root = native_root(tmp_path)
    assert [p["id"] for p in drawn_pages(DOC)] == ["PAGE-001", "PAGE-002", "PAGE-004"]
    assert not (root / "src/screens/PAGE-003.tsx").exists()
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
