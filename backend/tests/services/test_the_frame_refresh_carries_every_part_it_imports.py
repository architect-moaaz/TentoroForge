"""The dashboard layout the catch-up refreshes imports sibling components;
each one must be refreshed with it, or an app gets the import without the
file and every dashboard route 500s with "module not found". This happened
with OrgSwitcher and OutsideOrganisation on 2026-10-15: the layout that
imports them was listed, they were not. This guard keeps the frame set
closed under the layout's own local imports, so the next sibling added to
the layout cannot regress the same way.
"""
from __future__ import annotations

import re
from pathlib import Path

from services.smith import sync_app

FOUNDATION = Path(sync_app.__file__).resolve().parents[2] / "templates" / "app-foundation"
DASHBOARD = FOUNDATION / "src" / "app" / "(dashboard)"


def _local_imports(tsx: Path) -> set[str]:
    """The `./X` siblings a frame file imports."""
    return set(re.findall(r'from\s+"\./([A-Za-z0-9_]+)"', tsx.read_text("utf-8")))


def test_every_sibling_the_dashboard_frame_imports_is_refreshed_with_it():
    framed = {f.rsplit("/", 1)[-1] for f in sync_app.FRAME_FILES if "(dashboard)" in f}
    missing: dict[str, set[str]] = {}
    for rel in sync_app.FRAME_FILES:
        if "(dashboard)" not in rel:
            continue
        src = FOUNDATION / rel
        if not src.is_file():
            continue
        for name in _local_imports(src):
            if not (DASHBOARD / f"{name}.tsx").is_file():
                continue  # not a sibling component (a type, a hook) — no file to ship
            if f"{name}.tsx" not in framed:
                missing.setdefault(rel, set()).add(f"{name}.tsx")
    assert not missing, (
        "a refreshed dashboard frame file imports a sibling that FRAME_FILES does not carry, "
        f"so a turn would write the import and not the file: {missing}")


def test_the_two_that_broke_pcn4owv7_are_carried():
    framed = set(sync_app.FRAME_FILES)
    assert "src/app/(dashboard)/OrgSwitcher.tsx" in framed
    assert "src/app/(dashboard)/OutsideOrganisation.tsx" in framed
