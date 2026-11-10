"""A data import does not stop the app's next publish.

The seeder keeps its import log in `_forge_import_log`, made with raw SQL and
declared in no schema file. The schema push saw it as an unknown table; the
next time the schema gained a table it asked "created, or renamed from
_forge_import_log?", which a build cannot answer, and Criterion Refunds
(kkb5mzo3, 2026-11-03) could not be published after its hotels were imported.
"""
from pathlib import Path

from services.blueprint.assembly import DRIZZLE_CONFIG

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def test_the_push_never_reads_the_seeders_own_tables():
    for text in (DRIZZLE_CONFIG, (TEMPLATES / "app-foundation/drizzle.config.ts").read_text()):
        assert 'tablesFilter: ["!_forge_seed_meta", "!_forge_import_log"]' in text
    seed = (TEMPLATES / "runtime/seed.ts").read_text()
    assert "CREATE TABLE IF NOT EXISTS _forge_import_log" in seed and "CREATE TABLE IF NOT EXISTS _forge_seed_meta" in seed


def test_an_app_built_before_is_brought_in_step(tmp_path):
    from services.smith.sync_app import refresh_engine

    app = tmp_path / "app"
    app.mkdir()
    (app / "package.json").write_text("{}")
    old = DRIZZLE_CONFIG.replace('["!_forge_seed_meta", "!_forge_import_log"]', '["!_forge_seed_meta"]')
    (app / "drizzle.config.ts").write_text(old)
    changed = refresh_engine(app, {}, complete=False)
    assert "drizzle.config.ts" in changed
    assert 'tablesFilter: ["!_forge_seed_meta", "!_forge_import_log"]' in (app / "drizzle.config.ts").read_text()
    assert "drizzle.config.ts" not in refresh_engine(app, {}, complete=False), "once"
