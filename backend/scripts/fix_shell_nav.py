#!/usr/bin/env python3
"""Retrofit the mobile-nav fix onto ALREADY-generated apps.

New generations get the fix automatically: the app-foundation template ships it,
and `inject_runtime` runs the same guard on every generation (fresh or reused).
But apps that were generated BEFORE the fix — and won't be regenerated — still
carry the bug. This CLI lets the developer repair them in place.

The bug: the WideRail/IconRail chrome rails are `hidden md:flex`, so below 768px
they vanished with no mobile menu — the app looked like it had "no sidebar".

Usage
-----
    # fix one app
    python backend/scripts/fix_shell_nav.py output/7urwsxfi

    # fix every app under a directory (each immediate child that looks like an app)
    python backend/scripts/fix_shell_nav.py output

    # dry run — report what WOULD change, touch nothing
    python backend/scripts/fix_shell_nav.py output --dry-run

Exit code is 0 on success (including "nothing to do"), 1 only on an internal
error. The retrofit is transactional and idempotent: it edits a layout only when
it positively recognizes the buggy chrome structure, and leaves every other
layout byte-for-byte untouched — so it is always safe to run, even repeatedly.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `services` importable whether run from repo root or the backend dir.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.shell_nav_guard import ensure_mobile_nav, _WIDE_ICON_OLD  # noqa: E402


def _is_app_dir(p: Path) -> bool:
    """A generated app has a dashboard layout at this well-known path."""
    return (p / "src" / "app" / "(dashboard)" / "layout.tsx").exists()


def _targets(root: Path) -> list[Path]:
    if _is_app_dir(root):
        return [root]
    # Otherwise treat `root` as a parent of app dirs (e.g. output/).
    return sorted(c for c in root.iterdir() if c.is_dir() and _is_app_dir(c))


def main() -> int:
    ap = argparse.ArgumentParser(description="Retrofit the mobile-nav fix onto generated apps.")
    ap.add_argument("path", help="an app dir (output/<id>) or a parent of app dirs (output/)")
    ap.add_argument("--dry-run", action="store_true", help="report changes without writing")
    args = ap.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return 1

    targets = _targets(root)
    if not targets:
        print(f"No generated apps found under {root} (looked for src/app/(dashboard)/layout.tsx).")
        return 0

    patched = copied = ok = skipped = 0
    for app in targets:
        name = app.name
        if args.dry_run:
            # Read-only recognizer — the SAME logic the guard uses, so a dry run
            # predicts exactly what a real run would do, and touches nothing.
            layout = app / "src" / "app" / "(dashboard)" / "layout.tsx"
            text = layout.read_text(encoding="utf-8")
            if "{mobileNav}" in text and "import { MobileNav }" in text:
                print(f"  ok        {name}  (already has mobile nav)"); ok += 1
            elif _WIDE_ICON_OLD in text:
                print(f"  WOULD FIX {name}  (buggy chrome rails, no mobile nav)"); patched += 1
            else:
                print(f"  skip      {name}  (unrecognized layout — left untouched)"); skipped += 1
            continue

        r = ensure_mobile_nav(app)
        if r["layout_patched"]:
            print(f"  FIXED    {name}  (wired mobile nav into the chrome rails)"); patched += 1
        elif r["already_ok"]:
            print(f"  ok       {name}  (already has mobile nav)"); ok += 1
        elif r["mobilenav_copied"]:
            print(f"  partial  {name}  (copied MobileNav.tsx)"); copied += 1
        else:
            print(f"  skip     {name}  (unrecognized layout — left untouched)"); skipped += 1

    verb = "would fix" if args.dry_run else "fixed"
    print(
        f"\n{len(targets)} app(s) scanned: {patched} {verb}, {ok} already ok, "
        f"{skipped} skipped (untouched)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
