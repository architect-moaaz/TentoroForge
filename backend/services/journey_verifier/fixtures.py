"""Resolve fixture slugs to concrete filesystem paths.

Fixtures live at `backend/fixtures/` (committed, shared across apps) and
get copied into `<app>/journeys/fixtures/` at emit time so the app is
self-contained and the Playwright driver has a relative path that works
regardless of where the app is cloned.
"""
from __future__ import annotations

import shutil
from pathlib import Path


# Slug → repo-relative source path. Keep this small; each fixture must be
# committed alongside the platform.
BUILTIN_FIXTURES: dict[str, str] = {
    "product_image": "backend/fixtures/images/product-shoe.jpg",
    "product_image_alt": "backend/fixtures/images/product-headphones.jpg",
    "cv_pdf": "backend/fixtures/documents/sample-cv.pdf",
}


def resolve_fixtures(
    slugs: list[str],
    output_dir: Path,
    repo_root: Path,
) -> dict[str, str]:
    """Copy the requested fixtures into `<app>/journeys/fixtures/` and
    return the map `slug → app-relative path`.

    Silently drops fixtures that aren't in the registry — the emitter's
    contract with the driver is that only resolved slugs make it into the
    spec, so a missing fixture becomes a spec-level validation error, not
    a runtime one.
    """
    dest_dir = Path(output_dir) / "journeys" / "fixtures"
    dest_dir.mkdir(parents=True, exist_ok=True)

    out: dict[str, str] = {}
    for slug in slugs:
        src_rel = BUILTIN_FIXTURES.get(slug)
        if not src_rel:
            continue
        src = Path(repo_root) / src_rel
        if not src.exists():
            continue
        dest = dest_dir / src.name
        shutil.copyfile(src, dest)
        # Driver reads relative to __dirname (`journeys/`)
        out[slug] = f"fixtures/{src.name}"
    return out


def collect_needed_slugs(spec) -> list[str]:
    """Walk the JourneySpec, return every fixture slug any step references."""
    slugs: set[str] = set()
    for j in spec.journeys:
        for s in j.steps:
            if s.fixture:
                slugs.add(s.fixture)
    return sorted(slugs)
