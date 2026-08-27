"""Guard the generated-app shell against the 'no menus' class of demo bug.

Two intermittent failures were shipping:
  1. The custom chrome rails (wide-rail / icon-rail / right-rail / floating-rail)
     are `hidden md:flex`, so below 768px they vanished with NO mobile menu —
     apps looked like they had no sidebar at all (viewport-dependent, hit demos).
  2. The bottom dock capped the menu at 8 items (`.slice(0, 8)`), silently
     dropping pages 9+ — 'few menus missing'.

These assert the fixes stay in the template.
"""
import pathlib
import re

_LAYOUT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "templates" / "app-foundation" / "src" / "app" / "(dashboard)" / "layout.tsx"
)
_MOBILE = _LAYOUT.parent / "MobileNav.tsx"
_SRC = _LAYOUT.read_text()


def test_mobile_nav_component_exists():
    assert _MOBILE.exists(), "MobileNav.tsx (mobile drawer) must exist"
    m = _MOBILE.read_text()
    assert "md:hidden" in m, "MobileNav must be mobile-only (md:hidden)"
    assert "data-nav-item" in m and "data-nav-label" in m, "drawer must render real nav items"


def test_layout_imports_and_uses_mobile_nav():
    assert 'import { MobileNav }' in _SRC, "layout must import MobileNav"
    assert "const mobileNav = (" in _SRC, "layout must build the mobileNav element"


def test_every_rail_chrome_renders_the_mobile_nav():
    # Each `hidden md:flex` rail chrome shell must include {mobileNav}, or that
    # chrome has no navigation below 768px.
    for chrome in ("wide-rail", "icon-rail", "right-rail", "floating-rail"):
        # isolate the branch for this chrome up to the next `else if` / `else {`
        idx = _SRC.find(f'chrome === "{chrome}"')
        assert idx != -1, f"chrome branch {chrome} missing"
        branch = _SRC[idx: idx + 600]
        assert "{mobileNav}" in branch, (
            f"chrome '{chrome}' shell does not render the mobile nav — it would "
            f"show no menu below 768px"
        )


def test_dock_does_not_drop_menu_items():
    # The dock must not cap the item list (it scrolls instead).
    assert "flattenNav(props.groups).slice(0, 8)" not in _SRC, (
        "the dock caps the menu at 8 items — pages 9+ become unreachable"
    )
    # and it must be horizontally scrollable so a long menu still fits
    assert "overflow-x-auto" in _SRC


def test_rails_still_hidden_below_md_desktop_unchanged():
    # The desktop rails remain `hidden md:flex` (we ADD mobile, not change desktop).
    assert "hidden h-full shrink-0 flex-col overflow-y-auto md:flex" in _SRC


def test_layout_menu_is_never_empty():
    # loadNavProps must fall back to the schema registry so the rail is never
    # blank (the "no menus / no dashboard" failure).
    assert "schemaRegistryItems" in _SRC
    assert 'import { schemas } from "@/schemas/registry"' in _SRC
    assert "if (!groups.length) groups = schemaRegistryItems()" in _SRC


# ── The pipeline guard (retrofits reused output dirs the template can't reach) ──
import sys, tempfile  # noqa: E402
import pathlib as _pl  # noqa: E402

sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from services.shell_nav_guard import (  # noqa: E402
    ensure_mobile_nav, _WIDE_ICON_OLD, _RIGHT_FLOAT_OLD, _FLOAT_OLD, _DOCK_OLD,
)


def _write_layout(root: _pl.Path, body: str) -> _pl.Path:
    dash = root / "src" / "app" / "(dashboard)"
    dash.mkdir(parents=True)
    (dash / "layout.tsx").write_text(body)
    return dash / "layout.tsx"


# A minimal OLD (pre-fix) buggy layout: the chrome dispatch WITHOUT the mobile
# nav. Built from the guard's own anchors so it can never drift from them.
_OLD_BUGGY = (
    'import { ShellStateProvider } from "@tentoroforge/renderer";\n'
    "export default function L(){\n"
    + _WIDE_ICON_OLD + "\n" + _RIGHT_FLOAT_OLD + "\n" + _FLOAT_OLD + "\n" + _DOCK_OLD + "\n"
    "}\n"
)


def test_guard_patches_a_recognized_buggy_layout():
    with tempfile.TemporaryDirectory() as d:
        root = _pl.Path(d)
        lay = _write_layout(root, _OLD_BUGGY)
        r = ensure_mobile_nav(str(root))
        out = lay.read_text()
        assert r["layout_patched"] is True
        assert "const mobileNav = (" in out, "mobileNav element must be defined"
        assert 'import { MobileNav }' in out, "MobileNav must be imported"
        assert out.count("{mobileNav}") >= 3, "every rail chrome must render the mobile nav"
        assert "flattenNav(props.groups).slice(0, 8)" not in out, "dock cap must be removed"
        assert (lay.parent / "MobileNav.tsx").exists(), "MobileNav.tsx must be copied in"


def test_guard_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        root = _pl.Path(d)
        lay = _write_layout(root, _OLD_BUGGY)
        ensure_mobile_nav(str(root))
        once = lay.read_text()
        r2 = ensure_mobile_nav(str(root))
        assert r2["already_ok"] is True
        assert lay.read_text() == once, "second run must not change the file"


def test_guard_leaves_unrecognized_layout_byte_identical():
    # A library-SideNav layout has its OWN mobile burger — the guard must not
    # touch it, and must NOT leave an orphan MobileNav import behind.
    unrec = (
        'import { SideNav } from "@tentoroforge/library";\n'
        'import { ShellStateProvider } from "@tentoroforge/renderer";\n'
        "export default function L(){ return <SideNav/>; }\n"
    )
    with tempfile.TemporaryDirectory() as d:
        root = _pl.Path(d)
        lay = _write_layout(root, unrec)
        r = ensure_mobile_nav(str(root))
        assert r == {"mobilenav_copied": False, "layout_patched": False, "already_ok": False}
        assert lay.read_text() == unrec, "unrecognized layout must be untouched"
        assert "import { MobileNav }" not in lay.read_text(), "must not orphan an import"
        assert not (lay.parent / "MobileNav.tsx").exists(), "must not copy MobileNav in"
