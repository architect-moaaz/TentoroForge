"""Where an app reports its assistant analytics, and the salt behind its people's anonymous codes, survive a rebuild (2026-10-23).

The assembly rewrites the app's env file whole. A salt that changed would give every person a new anonymous code (their history split in
two); an address or key that vanished would make a live app silently stop reporting. A published app carries the salt, address and key, but
never the "include message text" choice: that is the builder's, per app, and defaults to off for a live one.
"""
from __future__ import annotations

from services.blueprint.assembly import INSIGHTS_KEYS, _SECRET_KEYS, existing_secrets

ENV = (
    "DATABASE_URL=x\nNEXTAUTH_SECRET=n1\n"
    "FORGE_INSIGHTS_USER_SALT=salt-1\nFORGE_INSIGHTS_URL=https://ttf.example/api/insights/ingest\n"
    "FORGE_INSIGHTS_KEY=fik_abc\nFORGE_INSIGHTS_INCLUDE_TEXT=1\n"
)


def test_the_insights_settings_are_kept_like_the_auth_secrets(tmp_path):
    (tmp_path / ".env.local").write_text(ENV)
    for k in INSIGHTS_KEYS:
        assert k in _SECRET_KEYS
    kept = existing_secrets(tmp_path)
    assert {k: kept[k] for k in INSIGHTS_KEYS} == {
        "FORGE_INSIGHTS_USER_SALT": "salt-1", "FORGE_INSIGHTS_URL": "https://ttf.example/api/insights/ingest",
        "FORGE_INSIGHTS_KEY": "fik_abc", "FORGE_INSIGHTS_INCLUDE_TEXT": "1",
    }


def test_the_env_file_a_rebuild_writes_carries_them_and_nothing_else_is_invented(tmp_path):
    from services.blueprint.assembly import assemble

    (tmp_path / ".env.local").write_text(ENV)
    doc = {"application": {"id": "t093w7a1", "name": "T"}}
    assemble(doc, tmp_path, project_short_id="t093w7a1")
    for name in (".env", ".env.local"):
        f = tmp_path / name
        if f.exists():
            body = f.read_text()
            assert "FORGE_INSIGHTS_USER_SALT=salt-1" in body, name
    rebuilt = (tmp_path / ".env").read_text()
    assert "FORGE_INSIGHTS_KEY=fik_abc" in rebuilt and "FORGE_INSIGHTS_URL=https://ttf.example/api/insights/ingest" in rebuilt
    # an app that never set them gets none invented: no salt of its own here (the runtime installer makes that one, once)
    (tmp_path / ".env").unlink()
    (tmp_path / ".env.local").unlink()
    assemble(doc, tmp_path, project_short_id="t093w7a1")
    assert "FORGE_INSIGHTS" not in (tmp_path / ".env").read_text()
