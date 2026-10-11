"""The tick authenticates itself with the app's own `CRON_SECRET`: written
with the auth secrets, kept across rebuilds, carried to the published
environment unless the org set one (2026-10-12)."""
from __future__ import annotations

from services.blueprint.assembly import _SECRET_KEYS, existing_secrets
from services.deploy.env_sync import build_deploy_env


def test_the_cron_secret_is_kept_like_the_auth_secrets(tmp_path):
    (tmp_path / ".env").write_text("DATABASE_URL=x\nNEXTAUTH_SECRET=n1\nCRON_SECRET=c1\n")
    assert "CRON_SECRET" in _SECRET_KEYS
    assert existing_secrets(tmp_path) == {"NEXTAUTH_SECRET": "n1", "CRON_SECRET": "c1"}


def test_the_published_app_carries_it_unless_the_org_set_one():
    env = build_deploy_env({}, "postgres://neon", "", "s", cron_secret="c1")
    assert env["CRON_SECRET"] == "c1"
    env = build_deploy_env({"CRON_SECRET": "org-wide"}, "postgres://neon", "", "s", cron_secret="c1")
    assert env["CRON_SECRET"] == "org-wide"
    assert "CRON_SECRET" not in build_deploy_env({}, "postgres://neon", "", "s")
