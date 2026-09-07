"""Tests for services.env_writer.write_env_local_from_platform.

The writer reads platform_integrations rows for an org, decrypts each
set value, and reconciles them with the generated app's .env.local:
managed keys land in a marker-delimited block; user-supplied keys
(DATABASE_URL, NEXTAUTH_SECRET, etc.) are preserved verbatim; cleared
rows drop their .env line.

These are unit-level tests — DB rows are mocked via a tiny stub because
the SQLAlchemy async session shape adds noise without new coverage.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _master_secret(monkeypatch):
    monkeypatch.setenv(
        "FORGE_INTEGRATIONS_SECRET",
        "test-master-secret-that-is-long-enough-1234567890",
    )


class _FakeExecResult:
    def __init__(self, rows):
        self._rows = rows
    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _FakeDB:
    """Just enough to satisfy `db.execute(select(...))` for both the
    PlatformIntegration and PlatformMcpServer queries the writer issues.
    Routes by inspecting the target class on the compiled Select."""
    def __init__(self, rows, mcp_rows=None):
        self._rows = rows
        self._mcp_rows = mcp_rows or []
    async def execute(self, query):
        # The writer issues `select(PlatformIntegration)` and
        # `select(PlatformMcpServer)` — inspect column_descriptions to
        # route without importing SQL layer machinery.
        entity_name = ""
        try:
            descs = query.column_descriptions
            if descs:
                entity = descs[0].get("entity")
                entity_name = getattr(entity, "__name__", "") if entity else ""
        except Exception:  # noqa: BLE001
            pass
        if entity_name == "PlatformMcpServer":
            return _FakeExecResult(self._mcp_rows)
        return _FakeExecResult(self._rows)


def _row(provider, key, plaintext):
    """Encrypt and shape as PlatformIntegration would look coming out of the DB."""
    from services.platform_integrations_crypto import encrypt
    ct, iv = encrypt(provider, plaintext)
    return SimpleNamespace(
        provider=provider, key=key, value_ct=ct, value_iv=iv,
    )


def _cleared_row(provider, key):
    return SimpleNamespace(provider=provider, key=key, value_ct=None, value_iv=None)


# --------------------------------------------------------------------------- #
# Basic write
# --------------------------------------------------------------------------- #

async def _call(tmp_path, rows, mcp_rows=None):
    from services.env_writer import write_env_local_from_platform
    return await write_env_local_from_platform(
        tmp_path, uuid.uuid4(), _FakeDB(rows, mcp_rows=mcp_rows),
    )


def _mcp_row(*, server_id=None, name="Firecrawl", url="https://mcp.firecrawl.dev",
             transport="http", auth_kind="bearer", secret="fc-tok",
             header_name=None, enabled=True):
    """Shape a PlatformMcpServer-like row. Encrypts `secret` via the real
    crypto module (provider='mcp')."""
    from services.platform_integrations_crypto import encrypt
    ct = iv = None
    if secret is not None and auth_kind != "none":
        ct, iv = encrypt("mcp", secret)
    return SimpleNamespace(
        id=server_id or uuid.uuid4(),
        name=name,
        server_url=url,
        transport=transport,
        auth_kind=auth_kind,
        auth_secret_ct=ct,
        auth_secret_iv=iv,
        auth_header_name=header_name,
        enabled=enabled,
    )


@pytest.mark.asyncio
async def test_writes_managed_block_when_platform_has_values(tmp_path):
    result = await _call(tmp_path, [
        _row("resend", "RESEND_API_KEY", "re_live"),
        _row("anthropic", "ANTHROPIC_API_KEY", "sk-ant-XYZ"),
    ])
    assert result["written"] is True
    env = (tmp_path / ".env.local").read_text(encoding="utf-8")
    assert "RESEND_API_KEY=re_live" in env
    assert "ANTHROPIC_API_KEY=sk-ant-XYZ" in env
    # Managed marker present exactly once.
    assert env.count("managed by Forge platform") == 1


@pytest.mark.asyncio
async def test_preserves_user_supplied_lines(tmp_path):
    (tmp_path / ".env.local").write_text(
        "DATABASE_URL=postgresql://x:y@localhost/z\n"
        "NEXTAUTH_SECRET=abc\n"
        "FORGE_URL=http://localhost:6500\n"
    )
    await _call(tmp_path, [_row("resend", "RESEND_API_KEY", "re_live")])
    env = (tmp_path / ".env.local").read_text(encoding="utf-8")
    assert "DATABASE_URL=postgresql://x:y@localhost/z" in env, "user URL wiped"
    assert "NEXTAUTH_SECRET=abc" in env, "user secret wiped"
    assert "FORGE_URL=http://localhost:6500" in env
    assert "RESEND_API_KEY=re_live" in env


@pytest.mark.asyncio
async def test_updates_existing_managed_value(tmp_path):
    (tmp_path / ".env.local").write_text(
        "DATABASE_URL=x\n"
        "RESEND_API_KEY=old_value\n"
    )
    await _call(tmp_path, [_row("resend", "RESEND_API_KEY", "new_value")])
    env = (tmp_path / ".env.local").read_text(encoding="utf-8")
    assert "old_value" not in env
    assert "RESEND_API_KEY=new_value" in env


@pytest.mark.asyncio
async def test_cleared_row_removes_line(tmp_path):
    (tmp_path / ".env.local").write_text(
        "DATABASE_URL=x\n"
        "RESEND_API_KEY=live_value\n"
    )
    result = await _call(tmp_path, [_cleared_row("resend", "RESEND_API_KEY")])
    env = (tmp_path / ".env.local").read_text(encoding="utf-8")
    assert "RESEND_API_KEY" not in env, "cleared row must remove the line"
    assert "DATABASE_URL=x" in env
    assert "RESEND_API_KEY" in result["cleared"]


@pytest.mark.asyncio
async def test_idempotent_no_write_when_unchanged(tmp_path):
    rows = [_row("resend", "RESEND_API_KEY", "re_live")]
    await _call(tmp_path, rows)
    r2 = await _call(tmp_path, rows)
    assert r2["written"] is False, "second call must be a no-op"


@pytest.mark.asyncio
async def test_unknown_key_reported_and_skipped(tmp_path):
    """A row whose key isn't in the spec registry (dead code, stale row)
    must be reported as skipped, never written to .env."""
    unknown = SimpleNamespace(
        provider="resend", key="ARBITRARY_UNKNOWN_KEY",
        value_ct="dummy", value_iv="dummy",
    )
    result = await _call(tmp_path, [unknown])
    env_path = tmp_path / ".env.local"
    if env_path.is_file():
        assert "ARBITRARY_UNKNOWN_KEY" not in env_path.read_text(encoding="utf-8")
    assert any(s["key"] == "ARBITRARY_UNKNOWN_KEY" for s in result["skipped"])


@pytest.mark.asyncio
async def test_decrypt_failure_skipped_not_crashing(tmp_path):
    """A row encrypted with a rotated master secret (or corrupted) MUST NOT
    take down the whole sync — skip that key, keep going."""
    bad = SimpleNamespace(
        provider="resend", key="RESEND_API_KEY",
        value_ct="not-real-base64-!!!!", value_iv="bad",
    )
    good = _row("anthropic", "ANTHROPIC_API_KEY", "sk-ant-good")
    result = await _call(tmp_path, [bad, good])
    env = (tmp_path / ".env.local").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-good" in env
    assert "RESEND_API_KEY" not in env
    assert any(s["key"] == "RESEND_API_KEY" and "decrypt" in s["reason"] for s in result["skipped"])


# --------------------------------------------------------------------------- #
# MCP servers → dynamic env vars
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_mcp_bearer_server_emits_all_env_vars(tmp_path):
    server_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    result = await _call(tmp_path, [], mcp_rows=[
        _mcp_row(server_id=server_id, auth_kind="bearer", secret="fc-abc"),
    ])
    env = (tmp_path / ".env.local").read_text(encoding="utf-8")
    slug = server_id.hex[:12].upper()
    assert f"MCP_SERVER_{slug}_URL=https://mcp.firecrawl.dev" in env
    assert f"MCP_SERVER_{slug}_TRANSPORT=http" in env
    assert f"MCP_SERVER_{slug}_AUTH_KIND=bearer" in env
    assert f"MCP_SERVER_{slug}_SECRET=fc-abc" in env
    assert result["mcp_servers"] == 1


@pytest.mark.asyncio
async def test_mcp_apikey_header_includes_header_name(tmp_path):
    server_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    await _call(tmp_path, [], mcp_rows=[
        _mcp_row(
            server_id=server_id,
            auth_kind="apikey_header",
            secret="k",
            header_name="X-Api-Key",
        ),
    ])
    env = (tmp_path / ".env.local").read_text(encoding="utf-8")
    slug = server_id.hex[:12].upper()
    assert f"MCP_SERVER_{slug}_AUTH_KIND=apikey_header" in env
    assert f"MCP_SERVER_{slug}_SECRET=k" in env
    assert f"MCP_SERVER_{slug}_AUTH_HEADER=X-Api-Key" in env


@pytest.mark.asyncio
async def test_mcp_none_auth_writes_no_secret(tmp_path):
    server_id = uuid.uuid4()
    await _call(tmp_path, [], mcp_rows=[
        _mcp_row(server_id=server_id, auth_kind="none", secret=None),
    ])
    env = (tmp_path / ".env.local").read_text(encoding="utf-8")
    slug = server_id.hex[:12].upper()
    assert f"MCP_SERVER_{slug}_AUTH_KIND=none" in env
    assert f"MCP_SERVER_{slug}_SECRET" not in env
    assert f"MCP_SERVER_{slug}_AUTH_HEADER" not in env


@pytest.mark.asyncio
async def test_disabled_mcp_server_removes_stale_env_lines(tmp_path):
    """A server previously emitted then disabled must have its env
    lines stripped on the next sync (managed-block rewrite)."""
    server_id = uuid.uuid4()
    # First pass — enabled, lines land.
    await _call(tmp_path, [], mcp_rows=[
        _mcp_row(server_id=server_id, auth_kind="bearer", secret="tok"),
    ])
    slug = server_id.hex[:12].upper()
    env = (tmp_path / ".env.local").read_text(encoding="utf-8")
    assert f"MCP_SERVER_{slug}_URL" in env

    # Second pass — no mcp rows returned (simulates disable/delete).
    await _call(tmp_path, [], mcp_rows=[])
    env2 = (tmp_path / ".env.local").read_text(encoding="utf-8")
    assert f"MCP_SERVER_{slug}_URL" not in env2
    assert f"MCP_SERVER_{slug}_SECRET" not in env2
