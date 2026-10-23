"""PR #28 review (2026-10-22): Metro, Expo and npm (and the install scripts of the packages it fetches) ran in the platform's
environment, so its database address, secret key and model keys reached code the phone project controls."""
import asyncio
import re
from pathlib import Path

from services import native_build
from services.phone_env import phone_env

SECRETS = {"DATABASE_URL": "postgres://u:p@h/db", "SECRET_KEY": "s3", "ANTHROPIC_API_KEY": "sk-a", "AWS_SECRET_ACCESS_KEY": "aws",
           "STRIPE_API_KEY": "sk_live", "GITHUB_TOKEN": "ghp", "SMTP_PASSWORD": "pw", "SENTRY_DSN": "https://x@sentry/1",
           "APP_PRIVATE_NOTE": "n"}


def _set(monkeypatch, extra=None):
    for k, v in {**SECRETS, "FORGE_FIXTURE_PLAIN": "kept", **(extra or {})}.items():
        monkeypatch.setenv(k, v)


def test_nothing_named_like_a_secret_reaches_the_phone_projects_processes(monkeypatch, tmp_path):
    _set(monkeypatch)
    env = phone_env(tmp_path)
    assert not (set(SECRETS) & set(env)), sorted(set(SECRETS) & set(env))


def test_what_a_toolchain_needs_is_kept_and_the_callers_values_win(monkeypatch, tmp_path):
    _set(monkeypatch)
    monkeypatch.setenv("CI", "")
    env = phone_env(tmp_path, CI="1", EXPO_OFFLINE="1")
    assert env.get("PATH") and env["FORGE_FIXTURE_PLAIN"] == "kept"
    assert env["CI"] == "1" and env["EXPO_OFFLINE"] == "1"


def test_a_name_in_the_projects_own_env_file_is_left_to_the_project(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_FIXTURE_APPVAR", "platform value")
    (tmp_path / ".env").write_text("FORGE_FIXTURE_APPVAR=app value\n")
    assert "FORGE_FIXTURE_APPVAR" not in phone_env(tmp_path)


def test_npm_runs_in_that_environment(monkeypatch, tmp_path):
    _set(monkeypatch)
    seen = {}

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"ok", None

    async def fake(exe, *args, **kw):
        seen.update(kw)
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
    native = tmp_path / "native"
    native.mkdir()
    assert asyncio.run(native_build._npm_run(["npm", "--version"], str(native), 10))[0] == 0
    assert seen["env"] and not (set(SECRETS) & set(seen["env"]))


def test_no_phone_module_hands_the_whole_platform_environment_to_a_process():
    root = Path(__file__).resolve().parents[2] / "services"
    for name in ("phone_live.py", "phone_preview.py", "native_build.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert not re.search(r"\*\*os\.environ|os\.environ\.items\(\)\s*if k != ", text), f"{name} spreads os.environ into a process"
