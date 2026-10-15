"""Thirteen pages as thirteen unlabeled icons in a 64px strip, three controls
stuffed into its foot (Personal Finance, 2026-10-15). Three rules: the chrome
pick weighs the menu, the icon rail keeps the groups it was given, and a
64px foot holds the bell and the avatar only."""
from __future__ import annotations

from pathlib import Path

from services.blueprint.projection import MAX_GLYPH_DESTINATIONS, derive_shell, menu_destinations

TPL = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "app" / "(dashboard)"
LAYOUT = (TPL / "layout.tsx").read_text()
ACCOUNT = (TPL / "AccountMenu.tsx").read_text()


def _doc(n: int, chrome: str = "icon-rail", grouped: bool = False) -> dict:
    pages = [{"id": f"p{i}", "route": f"/page-{i}", "title": f"Page {i}"} for i in range(n)]
    if grouped:
        tree = [{"label": "Money", "children": [{"page": p["id"], "label": p["title"]} for p in pages]}]
    else:
        tree = [{"page": p["id"], "label": p["title"]} for p in pages]
    return {"pages": pages, "navigation": {"tree": tree}, "designSystem": {"shell": {"chrome": chrome}}}


def test_the_chrome_pick_weighs_the_menu():
    assert MAX_GLYPH_DESTINATIONS == 8
    assert derive_shell(_doc(8))["chrome"] == "icon-rail"
    assert derive_shell(_doc(13))["chrome"] == "standard-rail"
    assert derive_shell(_doc(13, chrome="dock"))["chrome"] == "standard-rail"
    # Grouping does not hide the count: a group of thirteen is thirteen glyphs.
    assert derive_shell(_doc(13, grouped=True))["chrome"] == "standard-rail"
    # A rail with labels is left alone however long it is.
    assert derive_shell(_doc(13, chrome="wide-rail"))["chrome"] == "wide-rail"


def test_pages_the_tree_forgot_still_count_because_the_frame_appends_them():
    doc = _doc(6)
    doc["pages"] += [{"id": f"x{i}", "route": f"/extra-{i}", "title": f"Extra {i}"} for i in range(4)]
    doc["pages"].append({"id": "det", "route": "/page-0/[id]", "title": "Detail"})  # not a destination
    doc["pages"].append({"id": "login", "route": "/login", "title": "Sign in"})
    assert menu_destinations(doc) == 10
    assert derive_shell(doc)["chrome"] == "standard-rail"


def test_the_frame_applies_the_same_rule_to_the_chrome_the_design_named():
    assert "const MAX_GLYPH_DESTINATIONS = 8;" in LAYOUT
    assert "async function menuDestinations(): Promise<number>" in LAYOUT
    guard = LAYOUT[LAYOUT.index("let chrome = String((spec?.layout"):LAYOUT.index("return {", LAYOUT.index("let chrome = String((spec?.layout"))]
    assert "(await menuDestinations()) > MAX_GLYPH_DESTINATIONS" in guard
    assert 'chrome = "standard-rail";' in guard
    # The design-dna override is read before the guard, so it cannot undo it.
    assert guard.index("dna?.layout?.chrome") < guard.index("menuDestinations()")


def test_the_icon_rail_keeps_the_groups():
    body = LAYOUT[LAYOUT.index("function IconRail("):LAYOUT.index("function DockNav(")]
    assert "flattenNav(" not in body
    assert "props.groups.map((g, gi)" in body
    assert 'data-nav-group=""' in body
    assert 'data-nav-group-head=""' in body          # the group's own icon heads its children
    assert 'className="my-1.5 h-px w-6"' in body        # a hairline and some air between groups
    assert "gi > 0 &&" in body                          # no divider above the first group
    assert "subs.map((it) => leaf(it, 18))" in body


def test_a_sixty_four_pixel_foot_holds_the_bell_and_the_avatar_only():
    block = LAYOUT[LAYOUT.index('const compact = chromeName === "icon-rail";'):LAYOUT.index(") : null;", LAYOUT.index('const compact = chromeName'))]
    assert "{!compact && extras}" in block
    assert "<NotificationBell />" in block
    assert "compact={compact} extras={compact ? extras : undefined}" in block
    extras = block[block.index("const extras = ("):block.index(");", block.index("const extras = ("))]
    for ctl in ("<OrgSwitcher />", "<LanguageSwitch />", "<InstallButton />"):
        assert ctl in extras, ctl
    # The account menu takes them in, shows the avatar alone, and opens to the
    # right of a rail that sits on the left edge.
    assert "extras?: React.ReactNode;" in ACCOUNT
    assert 'data-account-extras=""' in ACCOUNT
    assert '{!compact && <span className="hidden max-w-[12ch] truncate sm:inline">' in ACCOUNT
    assert '(compact ? "left-0" : "right-0")' in ACCOUNT
    assert ACCOUNT.index('data-account-extras=""') < ACCOUNT.index("Sign out")
