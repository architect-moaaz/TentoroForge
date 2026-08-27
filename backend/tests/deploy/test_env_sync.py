"""Unit tests for build_deploy_env — merges integrations + Neon URL +
system vars into the final env-var map the deploy pipeline pushes to
Vercel."""
from __future__ import annotations

from services.deploy.env_sync import build_deploy_env


def test_merges_integrations_with_system_vars() -> None:
    env = build_deploy_env(
        integrations={"RESEND_API_KEY": "re_1", "ANTHROPIC_API_KEY": "sk_1"},
        neon_url="postgres://ep.neon.tech/main",
        vercel_url="acme.vercel.app",
        nextauth_secret="deadbeef",
    )
    assert env["DATABASE_URL"] == "postgres://ep.neon.tech/main"
    assert env["NEXTAUTH_URL"] == "https://acme.vercel.app"
    assert env["NEXTAUTH_SECRET"] == "deadbeef"
    assert env["RESEND_API_KEY"] == "re_1"
    assert env["ANTHROPIC_API_KEY"] == "sk_1"
    # NODE_ENV is a Vercel-reserved system var — Vercel sets it to
    # "production" automatically at build/deploy time, and pushing it via
    # the env-var API 403s. build_deploy_env correctly omits it.
    assert "NODE_ENV" not in env


def test_system_vars_override_conflicting_integrations() -> None:
    # A user pastes a stale DATABASE_URL in their platform integrations —
    # the Neon URL from THIS publish MUST win, else the app talks to the
    # wrong DB and the user is confused for hours.
    env = build_deploy_env(
        integrations={"DATABASE_URL": "postgres://oldwrong"},
        neon_url="postgres://ep.neon.tech/main",
        vercel_url="acme.vercel.app",
        nextauth_secret="x",
    )
    assert env["DATABASE_URL"] == "postgres://ep.neon.tech/main"


def test_skips_none_and_empty_integration_values() -> None:
    env = build_deploy_env(
        integrations={"OPTIONAL": None, "BLANK": "", "SET": "v"},
        neon_url="postgres://x",
        vercel_url="acme.vercel.app",
        nextauth_secret="s",
    )
    assert "OPTIONAL" not in env
    assert "BLANK" not in env
    assert env["SET"] == "v"


def test_prefixes_vercel_url_with_https() -> None:
    env = build_deploy_env(
        integrations={},
        neon_url="postgres://x",
        vercel_url="acme.vercel.app",  # Vercel returns bare host
        nextauth_secret="s",
    )
    assert env["NEXTAUTH_URL"] == "https://acme.vercel.app"


def test_strips_incoming_scheme_from_vercel_url() -> None:
    # Guard against double-scheme like "https://https://acme.vercel.app"
    env = build_deploy_env(
        integrations={},
        neon_url="postgres://x",
        vercel_url="https://acme.vercel.app",
        nextauth_secret="s",
    )
    assert env["NEXTAUTH_URL"] == "https://acme.vercel.app"


def test_blob_token_included_when_present() -> None:
    env = build_deploy_env(
        integrations={},
        neon_url="postgres://x",
        vercel_url="acme.vercel.app",
        nextauth_secret="s",
        blob_token="vercel_blob_rw_xxx",
    )
    assert env["BLOB_READ_WRITE_TOKEN"] == "vercel_blob_rw_xxx"


def test_blob_token_absent_when_not_provided() -> None:
    env = build_deploy_env(
        integrations={},
        neon_url="postgres://x",
        vercel_url="acme.vercel.app",
        nextauth_secret="s",
    )
    assert "BLOB_READ_WRITE_TOKEN" not in env
