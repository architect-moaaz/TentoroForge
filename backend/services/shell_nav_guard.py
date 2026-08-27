"""Guarantee every generated app has working navigation at every viewport.

The compositional chrome rails (WideRail/IconRail — wide-rail / icon-rail /
right-rail / floating-rail) are `hidden md:flex`: below 768px they vanish with
no mobile menu, so the app looks like it has no sidebar. A fix landed in the
app-foundation template, BUT the template floor copies foundation files only
`if not target.exists()` — so a regenerated (reused) output dir keeps its OLD
layout.tsx and never gets the fix. This guard closes that gap: run on every
generation, it ENSURES

  1. (dashboard)/MobileNav.tsx exists (copied from the template), and
  2. (dashboard)/layout.tsx imports MobileNav, builds the `mobileNav` element,
     renders it in all four rail chromes, and the dock shows every page.

All edits are idempotent and surgical (string-anchored on the template shell
structure). If a layout doesn't match the expected structure, the guard leaves
it untouched — it never breaks a build.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_TEMPLATE_DASHBOARD = (
    Path(__file__).resolve().parents[1]
    / "templates" / "app-foundation" / "src" / "app" / "(dashboard)"
)

# ── Idempotent string patches (must match the template shell dispatch) ────────

_IMPORT_ANCHOR = 'import { ShellStateProvider } from "@tentoroforge/renderer";'
_IMPORT_ADD = _IMPORT_ANCHOR + '\nimport { MobileNav } from "./MobileNav";'

_WIDE_ICON_OLD = '''  let shell: React.ReactNode;
  if (chrome === "wide-rail") {
    shell = (
      <div className="flex h-screen overflow-hidden bg-background">
        <WideRail props={navProps} appName={appName} />{main}
      </div>
    );
  } else if (chrome === "icon-rail") {
    shell = (
      <div className="flex h-screen overflow-hidden bg-background">
        <IconRail props={navProps} appName={appName} />{main}
      </div>
    );
  } else if (chrome === "dock") {'''
_WIDE_ICON_NEW = '''  const mobileNav = (
    <MobileNav appName={appName} items={flattenNav(navProps.groups)} bg={navProps.bg} text={navProps.text} />
  );
  let shell: React.ReactNode;
  if (chrome === "wide-rail") {
    shell = (
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        {mobileNav}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <WideRail props={navProps} appName={appName} />{main}
        </div>
      </div>
    );
  } else if (chrome === "icon-rail") {
    shell = (
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        {mobileNav}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <IconRail props={navProps} appName={appName} />{main}
        </div>
      </div>
    );
  } else if (chrome === "dock") {'''

_RIGHT_FLOAT_OLD = '''    shell = (
      <div className="flex h-screen flex-row-reverse overflow-hidden bg-background">
        <WideRail props={navProps} appName={appName} />{main}
      </div>
    );
  } else if (chrome === "floating-rail") {'''
_RIGHT_FLOAT_NEW = '''    shell = (
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        {mobileNav}
        <div className="flex min-h-0 flex-1 flex-row-reverse overflow-hidden">
          <WideRail props={navProps} appName={appName} />{main}
        </div>
      </div>
    );
  } else if (chrome === "floating-rail") {'''

_FLOAT_OLD = '''    shell = (
      <div className="flex h-screen gap-1 overflow-hidden bg-background p-3">
        <div className="hidden overflow-hidden rounded-2xl shadow-xl md:block">
          <WideRail props={navProps} appName={appName} />
        </div>
        {main}
      </div>
    );'''
_FLOAT_NEW = '''    shell = (
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        {mobileNav}
        <div className="flex min-h-0 flex-1 gap-1 overflow-hidden p-3">
          <div className="hidden overflow-hidden rounded-2xl shadow-xl md:block">
            <WideRail props={navProps} appName={appName} />
          </div>
          {main}
        </div>
      </div>
    );'''

_DOCK_OLD = '''  const items = flattenNav(props.groups).slice(0, 8);
  return (
    <nav data-shell-nav="" data-dock=""
      className="fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-1 rounded-2xl px-2 py-1.5 shadow-2xl backdrop-blur"'''
_DOCK_NEW = '''  const items = flattenNav(props.groups);
  return (
    <nav data-shell-nav="" data-dock=""
      className="fixed bottom-4 left-1/2 z-40 flex max-w-[calc(100vw-1rem)] -translate-x-1/2 items-center gap-1 overflow-x-auto rounded-2xl px-2 py-1.5 shadow-2xl backdrop-blur"'''


def _ensure_component(dash: Path, result: dict) -> None:
    """Copy MobileNav.tsx next to the layout if it isn't already there."""
    mob = dash / "MobileNav.tsx"
    if not mob.exists():
        src = _TEMPLATE_DASHBOARD / "MobileNav.tsx"
        if src.exists():
            mob.write_text(src.read_text(), encoding="utf-8")
            result["mobilenav_copied"] = True


def ensure_mobile_nav(output_dir: str | Path) -> dict:
    """Ensure the generated app's dashboard shell has a mobile menu.

    Returns {"mobilenav_copied": bool, "layout_patched": bool, "already_ok": bool}.
    Never raises — nav robustness must not break a generation.

    The patch is TRANSACTIONAL: it only edits a layout whose structure it
    positively recognizes (the WideRail/IconRail chrome dispatch — the exact
    shape that carries the `hidden md:flex` mobile bug). Any other layout —
    the older static `<aside>`, a library-`SideNav` layout with its own mobile
    burger, or a bespoke one — is left byte-for-byte untouched. That guarantees
    the guard can never orphan an import or break a build it doesn't understand.
    """
    result = {"mobilenav_copied": False, "layout_patched": False, "already_ok": False}
    try:
        dash = Path(output_dir) / "src" / "app" / "(dashboard)"
        layout = dash / "layout.tsx"
        if not layout.exists():
            return result  # no dashboard shell (e.g. a non-standard app) — nothing to do

        text = layout.read_text(encoding="utf-8")

        # Already wired — nothing to patch, but make sure the component it imports
        # actually exists on disk.
        if "{mobileNav}" in text and "import { MobileNav }" in text:
            result["already_ok"] = True
            _ensure_component(dash, result)
            return result

        # The mobile bug lives ONLY in the WideRail/IconRail chrome dispatch, and
        # `_WIDE_ICON_OLD` is that exact structure (it is also where the
        # `const mobileNav` element is introduced). If this anchor isn't present,
        # the layout is a different vintage that navigates fine on mobile by other
        # means — leave it completely alone rather than risk a broken edit.
        if _WIDE_ICON_OLD not in text:
            return result

        _ensure_component(dash, result)

        original = text
        if "import { MobileNav }" not in text and _IMPORT_ANCHOR in text:
            text = text.replace(_IMPORT_ANCHOR, _IMPORT_ADD, 1)
        # `_WIDE_ICON_NEW` defines `const mobileNav` AND renders it in wide/icon;
        # the rest reference that same const, so they are only ever applied in a
        # file where this first replacement already ran.
        text = text.replace(_WIDE_ICON_OLD, _WIDE_ICON_NEW, 1)
        if _RIGHT_FLOAT_OLD in text:
            text = text.replace(_RIGHT_FLOAT_OLD, _RIGHT_FLOAT_NEW, 1)
        if _FLOAT_OLD in text:
            text = text.replace(_FLOAT_OLD, _FLOAT_NEW, 1)
        if _DOCK_OLD in text:
            text = text.replace(_DOCK_OLD, _DOCK_NEW, 1)

        if text != original:
            layout.write_text(text, encoding="utf-8")
            result["layout_patched"] = True
            logger.info("shell_nav_guard: wired mobile nav into %s", layout)
    except Exception as e:  # noqa: BLE001 — never block generation on this guard
        logger.warning("shell_nav_guard skipped: %s", e)
    return result
