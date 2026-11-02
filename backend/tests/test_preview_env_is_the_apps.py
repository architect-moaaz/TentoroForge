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


def test_only_what_a_toolchain_needs_reaches_the_app(tmp_path, monkeypatch):
    """Audit, 2026-11-01: a list of names to take out missed what it did not
    know — the integrations key, deploy tokens, the apps database."""
    for key in ("FORGE_INTEGRATIONS_SECRET", "VERCEL_TOKEN", "NEON_API_KEY", "FORGE_APPS_DATABASE_URL",
                "AWS_SECRET_ACCESS_KEY", "SENDGRID_API_KEY", "SOME_NEW_PLATFORM_SETTING"):
        monkeypatch.setenv(key, "platform")
    monkeypatch.setenv("npm_config_cache", "/cache")
    monkeypatch.setenv("npm_config__authToken", "registry-token")
    monkeypatch.setenv("LC_ALL", "C")
    env = preview.app_env(str(tmp_path / "app"))
    assert not {k for k in env if env[k] in ("platform", "registry-token")}
    assert env["npm_config_cache"] == "/cache" and env["LC_ALL"] == "C"


def test_every_process_that_runs_app_code_gets_the_apps_environment():
    """A dev server, a build, a boot check, a page review, a journey run: each
    runs code a model wrote and packages it installed."""
    import inspect
    import re

    from services.blueprint import assembly, page_review
    from services.journey_verifier import boot, container, harness
    from services.react_editor import adapter, jit

    for module in (assembly, page_review, boot, container, harness, adapter, jit):
        source = inspect.getsource(module)
        assert not re.search(r"\*\*os\.environ|os\.environ\.copy\(\)|dict\(os\.environ\)", source), module.__name__
