"""The tab bar: distinct icons, and a More tab for the main pages that do not fit.

A bar holds five tabs with the account tab. An application with more main pages used to get NO bar at all (and so
no way to reach its pages); now the first pages get a tab and the rest are listed behind More. Two tabs never
share an icon, and every icon is a real Ionicons glyph."""
from __future__ import annotations

import json
import os
from pathlib import Path

from services.blueprint.native_projection import (
    MAX_TABS, _ICON_BY_NAME, _ICON_BY_PATTERN, _ICON_BY_WORD, _ICON_SPARE, more_pages, native_root, project_native,
    tab_icons, tab_pages,
)

NAMES = ["Dashboard", "Appointments", "Pets", "Owners", "Invoices", "Reports", "Stock"]


def app(count: int, *, sign_in: bool = True, mobile: str | None = "tabs") -> dict:
    pages = [{"id": f"PAGE-{i:03d}", "name": NAMES[i - 1], "route": f"/{NAMES[i - 1].lower()}", "access": "authenticated",
              "pattern": "entity_list"} for i in range(1, count + 1)]
    return {
        "application": {"name": "Paws"}, "mobile": {"native": {"enabled": True}}, "designSystem": {"colors": {"primary": "#6a4c93"}},
        "security": {} if sign_in else {"authentication": "none"}, "roles": [{"id": "ROLE-001", "name": "Staff"}],
        "data": {"entities": []}, "workflows": [], "pages": pages,
        "navigation": {"tree": [{"label": p["name"], "page": p["id"]} for p in pages],
                       **({"mobile": mobile} if mobile else {})},
        "nativeCode": [{"page": p["id"], "screen": "export default function Screen() { return null; }"} for p in pages],
    }


def test_four_main_pages_and_the_account_tab_fit_without_a_more_tab():
    assert len(tab_pages(app(4))) == 4 and more_pages(app(4)) == []


def test_more_main_pages_than_fit_go_behind_a_more_tab():
    doc = app(7)
    assert len(tab_pages(doc)) == MAX_TABS - 2, "three tabs, then More, then Account"
    assert [p["name"] for p in more_pages(doc)] == NAMES[3:]


def test_the_more_tab_is_written_and_lists_the_rest(tmp_path):
    project_native(app(6), tmp_path)
    root = native_root(tmp_path)
    nav = (root / "src" / "navigation.generated.ts").read_text("utf-8")
    assert nav.index('"name": "more"') < nav.index('"name": "account"')
    assert (root / "app/(tabs)/more.tsx").is_file()
    assert '"route": "/stock"' not in nav and '"route": "/reports"' in nav, "6 pages: the last three are listed, in the More list"
    # a page behind More opens ON TOP of the bar, not as a tab
    assert (root / "app/reports.tsx").is_file() and not (root / "app/(tabs)/reports.tsx").exists()


def test_the_more_tab_goes_when_the_pages_fit(tmp_path):
    project_native(app(6), tmp_path)
    root = native_root(tmp_path)
    project_native(app(3), tmp_path)
    assert not (root / "app/(tabs)/more.tsx").exists()
    assert '"name": "more"' not in (root / "src" / "navigation.generated.ts").read_text("utf-8")


def test_a_tab_bar_never_repeats_an_icon():
    icons = tab_icons([(None, "Pets", "entity_list"), (None, "Owners", "entity_list"), (None, "Reports", "entity_list"),
                       (None, "Misc", "entity_list"), (None, "Other", "entity_list")])
    assert len(set(icons)) == len(icons)
    assert icons[0] == "paw"


def test_an_icon_follows_the_pages_name_when_the_navigation_names_none():
    assert tab_icons([(None, "Invoices", "entity_list")]) == ["receipt"]
    assert tab_icons([("PawPrint", "Whatever", "entity_list")]) == ["paw"]
    assert tab_icons([(None, "Mystery", "form")]) == ["apps"]


def _glyphs() -> set[str] | None:
    root = os.environ.get("FORGE_NATIVE_TOOLCHAIN")
    if not root:
        return None
    found = next(iter(Path(root).rglob("glyphmaps/Ionicons.json")), None)
    return set(json.loads(found.read_text("utf-8"))) if found else None


def test_every_icon_is_a_real_ionicons_glyph():
    glyphs = _glyphs()
    if glyphs is None:
        import pytest
        pytest.skip("no native toolchain to read the Ionicons glyph map from")
    used = set(_ICON_BY_NAME.values()) | {g for _, g in _ICON_BY_WORD} | set(_ICON_BY_PATTERN.values()) | set(_ICON_SPARE)
    assert not sorted(used - glyphs), "not Ionicons glyphs"


# --- the other way to navigate: a hamburger menu ----------------------------------------------------------


def test_the_agent_decides_and_the_phone_follows():
    from services.blueprint.native_projection import nav_style
    assert nav_style(app(7, mobile="drawer")) == "drawer" and nav_style(app(3, mobile="drawer")) == "drawer"
    assert nav_style(app(7, mobile="tabs")) == "tabs", "tabs it said, so More holds the rest"


def test_with_no_decision_a_few_pages_are_a_bar_and_many_are_a_menu():
    from services.blueprint.native_projection import nav_style
    assert nav_style(app(4, mobile=None)) == "tabs"
    assert nav_style(app(7, mobile=None)) == "drawer"


def test_a_drawer_app_has_no_tab_bar_and_a_menu_of_every_main_page_then_account(tmp_path):
    from services.blueprint.native_projection import is_menu_page
    doc = app(6, mobile="drawer")
    assert tab_pages(doc) == [] and more_pages(doc) == []
    assert is_menu_page(doc, "PAGE-006") and not is_menu_page(app(6), "PAGE-001")
    project_native(doc, tmp_path)
    root = native_root(tmp_path)
    nav = (root / "src" / "navigation.generated.ts").read_text("utf-8")
    assert '"drawer"' in nav and '"route": "/stock"' not in nav and '"route": "/reports"' in nav
    assert nav.index('"route": "/reports"') < nav.index('"route": "/account"'), "Account is the last item"
    assert not (root / "app/(tabs)/_layout.tsx").exists()
    assert (root / "app/reports.tsx").is_file() and (root / "app/account.tsx").is_file()
    assert "Sign out" in (root / "app/account.tsx").read_text("utf-8")


def test_switching_a_drawer_app_to_tabs_moves_the_account_screen_into_the_bar(tmp_path):
    project_native(app(3, mobile="drawer"), tmp_path)
    root = native_root(tmp_path)
    project_native(app(3, mobile="tabs"), tmp_path)
    assert (root / "app/(tabs)/account.tsx").is_file() and not (root / "app/account.tsx").exists()
    assert '"NAV_STYLE"' not in (root / "src" / "navigation.generated.ts").read_text("utf-8")
    assert 'NAV_STYLE: "tabs" | "drawer" = "tabs"' in (root / "src" / "navigation.generated.ts").read_text("utf-8")


def test_the_header_draws_the_hamburger_on_a_menu_page_and_the_menu_lists_the_pages():
    kit = Path(__file__).resolve().parents[2] / "templates" / "native" / "src" / "ui"
    screen = (kit / "Screen.tsx").read_text("utf-8")
    assert "<MenuButton" in screen and "isMenuRoute" in screen and 'NAV_STYLE === "drawer"' in screen
    menu = (kit / "Menu.tsx").read_text("utf-8")
    assert "MENU.map" in menu and "router.replace" in menu, "a menu choice replaces the page; it does not stack a history"


def test_going_to_a_drawer_leaves_no_empty_tab_folder(tmp_path):
    project_native(app(3, mobile="tabs"), tmp_path)
    project_native(app(3, mobile="drawer"), tmp_path)
    assert not (native_root(tmp_path) / "app" / "(tabs)").exists()
