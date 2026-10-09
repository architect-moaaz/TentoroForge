"""A Preview runs in the app's environment, not the platform's.

It inherited the platform's (``{**os.environ}``), and Next.js lets the process
environment win over the app's ``.env`` files: every Preview read Forge's own
``DATABASE_URL``, so sign-in looked for its user in the platform's database
and answered 401 — and Forge's secrets and model keys reached every app.
"""
from __future__ import annotations

import preview


def test_the_platforms_settings_and_secrets_do_not_reach_the_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://appforge@localhost/appforge")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "platform-key")
    monkeypatch.setenv("SECRET_KEY", "platform-secret")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = preview.app_env(str(tmp_path), NEXT_BASE_PATH="/p")
    for key in ("DATABASE_URL", "ANTHROPIC_API_KEY", "SECRET_KEY"):
        assert key not in env
    assert env["PATH"] == "/usr/bin:/bin", "what a toolchain needs is kept"
    assert env["NEXT_BASE_PATH"] == "/p"


def test_what_the_app_sets_for_itself_is_its_own(tmp_path, monkeypatch):
    (tmp_path / ".env.local").write_text("# db\nexport STRIPE_KEY=app\nFEATURE_X=1\n")
    monkeypatch.setenv("STRIPE_KEY", "platform")
    monkeypatch.setenv("FEATURE_X", "0")
    env = preview.app_env(str(tmp_path))
    assert "STRIPE_KEY" not in env and "FEATURE_X" not in env


def test_anything_in_the_platforms_settings_file_stays_the_platforms(tmp_path, monkeypatch):
    settings = tmp_path / "platform.env"
    settings.write_text("SOME_PLATFORM_FLAG=on\n")
    monkeypatch.setattr(preview, "_PLATFORM_ENV_FILE", settings)
    monkeypatch.setenv("SOME_PLATFORM_FLAG", "on")
    assert "SOME_PLATFORM_FLAG" not in preview.app_env(str(tmp_path / "app"))
