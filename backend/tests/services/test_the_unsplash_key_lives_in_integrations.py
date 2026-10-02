"""The Unsplash key is set in Settings → Integrations and stays on the platform.

The `imagery` node searches Unsplash while an application is built; the app
only loads images.unsplash.com addresses. So the key is the organisation's,
resolved by the build from the integrations store — and, like the Figma and
UX Pilot keys, never written into an app's .env.local or a deployment's
environment, where every published app would carry the organisation's token.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from services.blueprint import imagery
from services.node_config_specs import all_providers, keys_for_provider, platform_only_keys


@pytest.fixture(autouse=True)
def _master_secret(monkeypatch):
    monkeypatch.setenv("FORGE_INTEGRATIONS_SECRET", "test-master-secret-that-is-long-enough-1234567890")


class _DB:
    """`execute(select(PlatformIntegration | PlatformMcpServer))` → rows."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, query):
        entity = (query.column_descriptions or [{}])[0].get("entity")
        rows = [] if getattr(entity, "__name__", "") == "PlatformMcpServer" else self._rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _row(provider, key, value):
    from services.platform_integrations_crypto import encrypt
    ct, iv = encrypt(provider, value)
    return SimpleNamespace(provider=provider, key=key, value_ct=ct, value_iv=iv, org_id=None)


def test_unsplash_is_a_card_on_the_settings_page_with_a_write_only_key():
    assert "unsplash" in all_providers()
    (key,) = keys_for_provider("unsplash")
    assert key.key == imagery.UNSPLASH_KEY_ENV and key.kind == "password"
    assert key.platform_only and key.help_url


def test_only_the_platform_reads_the_design_and_photo_keys():
    assert {"UNSPLASH_ACCESS_KEY", "FIGMA_TOKEN", "UXPILOT_API_KEY"} <= platform_only_keys()
    assert not {"RESEND_API_KEY", "ANTHROPIC_API_KEY"} & platform_only_keys()


@pytest.mark.asyncio
async def test_an_apps_env_never_gets_the_key_and_loses_an_old_copy(tmp_path):
    from services.env_writer import _MANAGED_MARKER, write_env_local_from_platform
    (tmp_path / ".env.local").write_text(f"DATABASE_URL=postgresql://x\n{_MANAGED_MARKER}\nFIGMA_TOKEN=figd_old\n")
    await write_env_local_from_platform(tmp_path, uuid.uuid4(), _DB([
        _row("unsplash", "UNSPLASH_ACCESS_KEY", "unsplash-secret"),
        _row("figma", "FIGMA_TOKEN", "figd_secret"),
        _row("resend", "RESEND_API_KEY", "re_live"),
    ]))
    env = (tmp_path / ".env.local").read_text()
    assert "RESEND_API_KEY=re_live" in env and "DATABASE_URL=postgresql://x" in env
    assert "unsplash-secret" not in env and "UNSPLASH_ACCESS_KEY" not in env
    assert "figd" not in env


@pytest.mark.asyncio
async def test_a_published_app_is_not_given_the_key():
    from routers.deployments import _collect_integrations
    out = await _collect_integrations(uuid.uuid4(), _DB([
        _row("unsplash", "UNSPLASH_ACCESS_KEY", "unsplash-secret"),
        _row("resend", "RESEND_API_KEY", "re_live"),
    ]))
    assert out == {"RESEND_API_KEY": "re_live"}


def test_the_build_uses_the_organisations_key(monkeypatch, tmp_path):
    monkeypatch.delenv(imagery.UNSPLASH_KEY_ENV, raising=False)
    asked = []

    def config_for(output_dir, provider="figma"):
        asked.append((str(output_dir), provider))
        return {"UNSPLASH_ACCESS_KEY": "org-key"}
    monkeypatch.setattr("services.figma.integrations.config_for", config_for)
    used = []
    monkeypatch.setattr(imagery, "_unsplash", lambda key: used.append(key) or (lambda p, q: {"results": []}))
    doc = {"designSystem": {"imagery": [{"role": "auth", "query": "tools"}]}}
    imagery.fill_imagery(doc, output_dir=tmp_path)
    assert asked == [(str(tmp_path), "unsplash")] and used == ["org-key"]


def test_the_environment_still_works_when_nothing_is_stored(monkeypatch, tmp_path):
    monkeypatch.setattr("services.figma.integrations.config_for", lambda output_dir, provider="figma": {})
    monkeypatch.setenv(imagery.UNSPLASH_KEY_ENV, "env-key")
    assert imagery.access_key(tmp_path) == "env-key"
    monkeypatch.delenv(imagery.UNSPLASH_KEY_ENV)
    assert imagery.access_key(tmp_path) == ""
