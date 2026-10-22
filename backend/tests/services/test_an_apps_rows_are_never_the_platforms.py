"""Smith reads and writes an application's rows in the application's own
database — never the platform's. With no preview running, the address used
to fall back to the process's own DATABASE_URL: on forge-v3, Forge's
database. Refreshing Personal Finance's sample rows reached for it and failed
only because it was written for the async driver (u8w3uw4j, 2026-10-22)."""
from __future__ import annotations

from services.smith.data_import import database_url


def _app(tmp_path, env_line: str | None):
    (tmp_path / "app").mkdir()
    if env_line is not None:
        (tmp_path / "app" / ".env.local").write_text(env_line + "\n")
    return tmp_path


def test_the_platforms_own_database_is_never_used(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://forge:secret@postgres:5432/forge")
    monkeypatch.setattr("services.preview_manager.get_environment_status", lambda short: {}, raising=False)
    assert database_url(_app(tmp_path, None)) == ""


def test_the_app_opens_what_its_own_settings_say(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://forge:secret@postgres:5432/forge")
    monkeypatch.setattr("services.preview_manager.get_environment_status", lambda short: {}, raising=False)
    out = _app(tmp_path, "DATABASE_URL=postgresql://app:pw@apps-db:5432/app_u8w3uw4j")
    assert database_url(out) == "postgresql://app:pw@apps-db:5432/app_u8w3uw4j"


def test_a_driver_in_the_scheme_is_dropped_for_psycopg2(tmp_path, monkeypatch):
    monkeypatch.setattr("services.preview_manager.get_environment_status", lambda short: {}, raising=False)
    out = _app(tmp_path, "DATABASE_URL=postgresql+asyncpg://app:pw@apps-db:5432/app_x")
    assert database_url(out) == "postgresql://app:pw@apps-db:5432/app_x"
