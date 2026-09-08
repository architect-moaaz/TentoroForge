"""Publish refreshes platform-owned files onto already-generated apps.

seed.ts is platform-owned (its logic is the same for every app; per-app data
lives in seed.json), and its template path differs from the app path
(templates/runtime/seed.ts -> src/db/seed.ts). A fix to it — e.g. always
ensuring the admin user exists even when FORGE_KEEP_DB_STATE preserves domain
data — must reach existing projects on their next publish.
"""
from pathlib import Path

from services.deploy.vercel_provider import (
    _refresh_platform_files,
    _TEMPLATE_RUNTIME_DIR,
)


def test_publish_refreshes_seed_ts_from_the_runtime_template(tmp_path: Path):
    # A stale seed.ts from an older generation.
    dst = tmp_path / "src" / "db" / "seed.ts"
    dst.parent.mkdir(parents=True)
    dst.write_text("// stale generated seed")

    _refresh_platform_files(tmp_path)

    refreshed = dst.read_text()
    template = (_TEMPLATE_RUNTIME_DIR / "seed.ts").read_text()
    assert refreshed == template, "seed.ts must be refreshed from the template"
    # And the current template ensures the admin before any skip gate.
    assert "const adminId = await seedAdmin();" in refreshed
    assert refreshed.index("await seedAdmin()") < refreshed.index('FORGE_KEEP_DB_STATE === "1"')


def test_refresh_creates_the_db_dir_when_absent(tmp_path: Path):
    # A project tree with no src/db yet — refresh must create it, not crash.
    _refresh_platform_files(tmp_path)
    assert (tmp_path / "src" / "db" / "seed.ts").is_file()
