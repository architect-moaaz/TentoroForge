"""An application's own keys outlive the platform's integrations sync.

Each app is made with its own sealing key (SENSITIVE_ENCRYPTION_KEY, for its
sensitive fields) and Web Push pair. The integrations writer
(`services.env_writer`) rewrites `.env.local` whenever an org's settings are
saved, and dropped every key the registry knows that the org had not set —
these included. On forge-v3, 38 of 42 apps had lost both: nothing could be
sealed (a Mews property's token was refused with a 500 on gvrhwft9), what was
sealed before could not be opened, and every push subscription was orphaned
(2026-11-03). The keys are now the app's: kept above the managed block,
replaced only by a value the org sets, and made once for an app that has none.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from services.env_writer import _MANAGED_MARKER, APP_OWNED

KEY = "SENSITIVE_ENCRYPTION_KEY=c2VhbGluZy1rZXktb2YtdGhpcy1hcHAtMzItYnl0ZXM="
VAPID = "VAPID_PRIVATE_KEY=app-own-private"


@pytest.fixture(autouse=True)
def _master_secret(monkeypatch):
    monkeypatch.setenv("FORGE_INTEGRATIONS_SECRET", "test-master-secret-that-is-long-enough-1234567890")


class _DB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, query):
        try:
            entity = query.column_descriptions[0].get("entity")
        except Exception:  # noqa: BLE001
            entity = None
        rows = [] if getattr(entity, "__name__", "") == "PlatformMcpServer" else self.rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _row(provider, key, plaintext):
    from services.platform_integrations_crypto import encrypt
    ct, iv = encrypt(provider, plaintext)
    return SimpleNamespace(provider=provider, key=key, value_ct=ct, value_iv=iv)


async def _sync(root, rows):
    from services.env_writer import write_env_local_from_platform
    return await write_env_local_from_platform(root, uuid.uuid4(), _DB(rows))


@pytest.mark.asyncio
async def test_the_apps_sealing_key_and_push_pair_survive_a_sync(tmp_path):
    (tmp_path / ".env.local").write_text(f"DATABASE_URL=postgres://x\n{KEY}\n{VAPID}\n")
    await _sync(tmp_path, [_row("resend", "RESEND_API_KEY", "re_live")])
    env = (tmp_path / ".env.local").read_text()
    assert KEY in env and VAPID in env
    assert "RESEND_API_KEY=re_live" in env
    await _sync(tmp_path, [])
    again = (tmp_path / ".env.local").read_text()
    assert again.count("SENSITIVE_ENCRYPTION_KEY=") == 1 and KEY in again, "kept, once, through every sync"


@pytest.mark.asyncio
async def test_a_key_the_org_sets_replaces_the_apps(tmp_path):
    (tmp_path / ".env.local").write_text(f"{KEY}\n")
    await _sync(tmp_path, [_row("encryption", "SENSITIVE_ENCRYPTION_KEY", "b3JnLXNldC1rZXk=")])
    env = (tmp_path / ".env.local").read_text()
    assert KEY not in env and env.count("SENSITIVE_ENCRYPTION_KEY=") == 1
    assert "SENSITIVE_ENCRYPTION_KEY=b3JnLXNldC1rZXk=" in env


def test_the_owned_keys_are_the_ones_an_app_makes_for_itself():
    assert APP_OWNED == {"SENSITIVE_ENCRYPTION_KEY", "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"}


def test_an_app_without_a_sealing_key_gets_one_above_the_managed_block(tmp_path):
    from services.runtime_injector import ensure_sensitive_key
    env = tmp_path / ".env.local"
    env.write_text(f"DATABASE_URL=postgres://x\nSENSITIVE_ENCRYPTION_KEY=\n\n{_MANAGED_MARKER}\nRESEND_API_KEY=re\n")
    assert ensure_sensitive_key(env) is True
    lines = env.read_text().splitlines()
    keyed = [i for i, ln in enumerate(lines) if ln.startswith("SENSITIVE_ENCRYPTION_KEY=")]
    assert len(keyed) == 1 and keyed[0] < lines.index(_MANAGED_MARKER), "above the block the writer rewrites"
    import base64
    assert len(base64.b64decode(lines[keyed[0]].split("=", 1)[1])) == 32, "an AES-256 key"
    first = env.read_text()
    assert ensure_sensitive_key(env) is False and env.read_text() == first, "a key that is there is never replaced"


@pytest.mark.asyncio
async def test_a_backfilled_key_survives_the_next_sync(tmp_path):
    from services.runtime_injector import ensure_sensitive_key
    env = tmp_path / ".env.local"
    env.write_text(f"DATABASE_URL=postgres://x\n\n{_MANAGED_MARKER}\nRESEND_API_KEY=re\n")
    ensure_sensitive_key(env)
    made = next(ln for ln in env.read_text().splitlines() if ln.startswith("SENSITIVE_ENCRYPTION_KEY="))
    await _sync(tmp_path, [_row("resend", "RESEND_API_KEY", "re_live")])
    assert made in env.read_text()


def test_smiths_sync_gives_a_mews_app_its_key(tmp_path):
    from services.smith.sync_app import refresh_engine
    (tmp_path / "src" / "lib" / "workflows").mkdir(parents=True)
    (tmp_path / "src" / "auth.ts").write_text("export {};")
    (tmp_path / "src" / "lib" / "account.ts").write_text("export const ADMIN_ROLE = null;")
    (tmp_path / "src" / "lib" / "tenancy.ts").write_text("export const isPlatformRole = () => false;")
    (tmp_path / ".env.local").write_text(f"DATABASE_URL=postgres://x\n\n{_MANAGED_MARKER}\nMEWS_CLIENT_TOKEN=ct\n")
    changed = refresh_engine(tmp_path, None, complete=False)
    assert ".env.local" in changed
    assert any(ln.startswith("SENSITIVE_ENCRYPTION_KEY=") and len(ln) > 30 for ln in (tmp_path / ".env.local").read_text().splitlines())


def test_the_injector_fills_push_keys_above_the_block_too(tmp_path):
    from services.runtime_injector import _ensure_env_file
    env = tmp_path / ".env.local"
    env.write_text(f"DATABASE_URL=postgres://x\n\n{_MANAGED_MARKER}\nRESEND_API_KEY=re\n")
    _ensure_env_file(tmp_path)
    lines = env.read_text().splitlines()
    marker = lines.index(_MANAGED_MARKER)
    for name in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "SENSITIVE_ENCRYPTION_KEY"):
        at = [i for i, ln in enumerate(lines) if ln.startswith(name + "=")]
        assert at and at[0] < marker, name
