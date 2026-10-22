"""The Editor's phone side: the same page, menu and look edits, followed by a rewrite of the phone app.

A page, the menu and the look are edits of the one Blueprint; the web app and the phone app are both projected from it. The
Editor used to rewrite only the web files, so a menu or colour changed while looking at the phone app reached it only at the next
build. Now every surface the application has is rewritten, and the pages list says which pages are phone screens."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.blueprint.service import BlueprintService
from services.react_editor import pages, phone, service, theme

SCREEN = 'export default function Screen() { return null; }\n'


def project(tmp_path, monkeypatch, *, native=True, surface="web_native"):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Cart Buddy", domain="ops")
    doc = svc.doc
    doc["pages"] = [
        {"id": "PAGE-001", "name": "Shopping List", "route": "/", "purpose": "The list.", "access": "authenticated", "pattern": "entity_list"},
        {"id": "PAGE-002", "name": "Bought", "route": "/bought", "purpose": "What was bought.", "access": "authenticated", "pattern": "entity_list"},
        {"id": "PAGE-004", "name": "Sign in", "route": "/login", "purpose": "In.", "access": "public", "pattern": "auth", "auth": "login"},
    ]
    doc["navigation"] = {"style": "topbar", "tree": [{"label": "Shopping List", "page": "PAGE-001"}, {"label": "Bought", "page": "PAGE-002"}]}
    doc["mobile"] = {"surface": surface, **({"native": {"enabled": True}, "store": {"bundleId": "com.example.cartbuddy"}} if native else {})}
    if native:
        doc["nativeCode"] = [{"page": "PAGE-001", "screen": SCREEN}, {"page": "PAGE-002", "screen": SCREEN}]
    doc["designSystem"] = {"colors": {"primary": "#2563EB", "background": "#F8FAFC", "text": "#0B1220", "border": "#E2E8F0"},
                           "typography": {"fontFamily": "Inter, system-ui, sans-serif"}, "radius": {"sm": "4px", "md": "8px", "lg": "12px"}}
    svc.save()
    (tmp_path / "app" / "src" / "app").mkdir(parents=True)
    (tmp_path / "app" / "package.json").write_text("{}")
    monkeypatch.setattr("services.smith.page_change._project", lambda svc, app_root: [])
    monkeypatch.setattr("services.blueprint.projection.project_public_nav", lambda doc, root: "")
    monkeypatch.setattr(pages, "project_code_pages", lambda doc, root: [])
    return service.locate(tmp_path)


# ---- which surfaces an application has --------------------------------------------------------------------------

def test_the_surfaces_follow_the_choice_of_where_people_use_the_app():
    assert phone.surfaces({"mobile": {"surface": "web"}}) == {"web": True, "phone": False}
    assert phone.surfaces({"mobile": {"surface": "web_native", "native": {"enabled": True}}}) == {"web": True, "phone": True}
    assert phone.surfaces({"mobile": {"surface": "native_only", "native": {"enabled": True}}}) == {"web": False, "phone": True}
    assert phone.surfaces({}) == {"web": True, "phone": False}          # an app made before the choice existed


def test_the_pages_list_says_which_pages_are_phone_screens_and_which_surfaces_exist(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch)
    listing = service.pages(service.load_blueprint(p).doc)
    by = {row["id"]: row for row in listing["pages"]}
    assert by["PAGE-001"]["phone"] is True and by["PAGE-002"]["phone"] is True
    assert by["PAGE-004"]["phone"] is False        # the sign-in screen is the kit's own, not a screen written for the page
    assert listing["surfaces"] == {"web": True, "phone": True}


def test_a_web_only_app_has_no_phone_pages(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, native=False, surface="web")
    listing = service.pages(service.load_blueprint(p).doc)
    assert not any(row["phone"] for row in listing["pages"]) and listing["surfaces"] == {"web": True, "phone": False}


# ---- an edit reaches the phone app ------------------------------------------------------------------------------

def test_a_menu_change_rewrites_the_phone_apps_menu(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch)
    pages.set_navigation(p, {"tree": [{"label": "Bought items", "page": "PAGE-002"}, {"label": "My list", "page": "PAGE-001"}]})
    nav = (tmp_path / "native" / "src" / "navigation.generated.ts").read_text(encoding="utf-8")
    assert nav.index("Bought items") < nav.index("My list"), "the phone's menu is in the order the person set"


def test_a_look_change_rewrites_the_phone_apps_theme(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch)
    theme.update(p, {"colors": {"primary": "#B91C1C"}})
    text = (tmp_path / "native" / "src" / "theme.generated.ts").read_text(encoding="utf-8")
    # The phone's theme keeps colours as the web's HSL triplets: #B91C1C is 0 74% 42%.
    assert '"primary": "0 74% 42%"' in text


def test_a_rename_reaches_the_phone_apps_menu_label(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch)
    pages.update(p, "PAGE-002", {"name": "Already bought"})
    nav = (tmp_path / "native" / "src" / "navigation.generated.ts").read_text(encoding="utf-8")
    assert "Already bought" in nav


def test_an_app_with_no_phone_app_is_left_alone(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, native=False, surface="web")
    pages.set_navigation(p, {"tree": [{"label": "Bought", "page": "PAGE-002"}]})
    theme.update(p, {"colors": {"primary": "#B91C1C"}})
    assert not (tmp_path / "native").exists()


def test_the_phone_project_that_cannot_be_rewritten_never_fails_the_edit(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch)

    def broken(doc, root):
        raise OSError("disk full")

    monkeypatch.setattr("services.blueprint.native_projection.project_generated_modules", broken)
    out = pages.set_navigation(p, {"tree": [{"label": "Bought", "page": "PAGE-002"}]})
    assert out["navigation"]["tree"][0]["label"] == "Bought"           # saved in the Blueprint; the next build writes the phone files


def test_the_phones_own_fixed_files_are_not_touched_by_an_edit(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch)
    native = tmp_path / "native"
    native.mkdir(exist_ok=True)
    (native / "app.json").write_text('{"expo": {"owner": "tentoro", "extra": {"appUrl": "https://live.example"}}}', encoding="utf-8")
    pages.set_navigation(p, {"tree": [{"label": "Bought", "page": "PAGE-002"}]})
    theme.update(p, {"colors": {"primary": "#B91C1C"}})
    assert (native / "app.json").read_text(encoding="utf-8") == '{"expo": {"owner": "tentoro", "extra": {"appUrl": "https://live.example"}}}'


# ---- saving the menu when the plan has the platform's own landing entries (2026-10-22) -------------------------------------

def _landings(p, **held):
    svc = service.load_blueprint(p)
    svc.doc["navigation"]["initialRoute"] = {"default": "/", **held}
    svc.save()


def test_a_menu_is_saved_when_the_plan_has_signed_in_and_signed_out_landings(tmp_path, monkeypatch):
    """"'authenticated' is not a kind of user of this application, so it has no landing" saved nothing, from a plan the platform wrote."""
    p = project(tmp_path, monkeypatch)
    _landings(p, authenticated="/", unauthenticated="/login")
    out = pages.set_navigation(p, {"tree": [{"label": "Bought", "page": "PAGE-002"}, {"label": "My list", "page": "PAGE-001"}]})
    assert [n["label"] for n in out["navigation"]["tree"]] == ["Bought", "My list"]
    assert service.load_blueprint(p).doc["navigation"]["initialRoute"] == {"default": "/", "authenticated": "/", "unauthenticated": "/login"}


def test_choosing_the_first_page_keeps_the_other_landings(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch)
    _landings(p, authenticated="/", unauthenticated="/login")
    pages.set_navigation(p, {"initialRoute": "/bought"})
    assert service.load_blueprint(p).doc["navigation"]["initialRoute"] == {"default": "/bought", "authenticated": "/", "unauthenticated": "/login"}


def test_a_landing_for_someone_who_is_not_a_kind_of_user_is_still_refused(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch)
    _landings(p, guest="/")
    with pytest.raises(service.EditorError) as e:
        pages.set_navigation(p, {"tree": [{"label": "Bought", "page": "PAGE-002"}]})
    assert e.value.code == "bad-menu" and "'guest' is not a kind of user" in str(e.value)


def test_a_landing_that_leads_nowhere_is_still_refused_for_the_signed_in(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch)
    _landings(p, authenticated="/nowhere")
    with pytest.raises(service.EditorError) as e:
        pages.set_navigation(p, {"tree": [{"label": "Bought", "page": "PAGE-002"}]})
    assert "landing route" in str(e.value)
