"""A publish pins NEXTAUTH_URL to the project's production alias only when
the Blueprint declares an identity provider (the provider admits only the
registered redirect); the SAML bridge is a hosted service reached by name,
and a SAML connection is registered with the enterprise's metadata
(2026-10-12)."""
from __future__ import annotations

import json

import pytest

from services.deploy.env_sync import build_deploy_env
from services.deploy.sign_in_address import callback_addresses, production_alias, published_address, sso_declared
from services.sso import jackson_client


def test_the_address_is_pinned_only_for_a_provider():
    env = build_deploy_env(integrations={}, neon_url="postgres://n", vercel_url="", nextauth_secret="s")
    assert "NEXTAUTH_URL" not in env
    env = build_deploy_env(integrations={}, neon_url="postgres://n", vercel_url="", nextauth_secret="s", nextauth_url="https://ledger.vercel.app/")
    assert env["NEXTAUTH_URL"] == "https://ledger.vercel.app"


def test_the_alias_comes_from_the_blueprint_on_disk(tmp_path):
    app = tmp_path / "app"
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps({"security": {"signIn": {"sso": [{"id": "entra", "name": "M"}]}}}))
    app.mkdir()
    assert sso_declared(app) and published_address(app, "ledger") == "https://ledger.vercel.app"
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps({"security": {}}))
    assert not sso_declared(app) and published_address(app, "ledger") == ""
    assert production_alias("ledger") == "https://ledger.vercel.app"
    assert callback_addresses("https://ledger.vercel.app", ["entra"]) == ["https://ledger.vercel.app/api/auth/callback/entra"]
    src = open(published_address.__code__.co_filename.replace("sign_in_address.py", "vercel_provider.py")).read()
    assert "published_address(snapshot.output_dir" in src and "and not nextauth_url:" in src


def test_the_bridge_is_reached_by_name_and_registers_the_enterprises_metadata():
    assert not jackson_client.configured({})
    assert jackson_client.configured({"JACKSON_URL": "https://sso.forge.test/", "JACKSON_API_KEY": "k"})
    body = jackson_client.connection_body("proj-1", "https://ledger.vercel.app", "corp", metadata_xml="<xml/>")
    assert body["tenant"] == "proj-1" and body["product"] == "forge" and body["rawMetadata"] == "<xml/>"
    assert body["redirectUrl"] == ["https://ledger.vercel.app/api/auth/callback/corp"]
    with pytest.raises(ValueError):
        jackson_client.connection_body("p", "https://a", "corp")
    with pytest.raises(RuntimeError) as e:
        jackson_client.register_saml("p", "https://a", "corp", metadata_url="https://idp/metadata", env={})
    assert "not hosted here" in str(e.value)


def test_a_registered_connection_fills_the_entrys_three_names(monkeypatch):
    monkeypatch.setattr(jackson_client, "_call", lambda m, p, b, env=None: {"clientID": "cid", "clientSecret": "csec"})
    got = jackson_client.register_saml("p", "https://a", "corp", metadata_xml="<x/>", env={"JACKSON_URL": "https://sso.test", "JACKSON_API_KEY": "k"})
    assert got == {"SSO_CORP_ISSUER": "https://sso.test", "SSO_CORP_CLIENT_ID": "cid", "SSO_CORP_CLIENT_SECRET": "csec"}


def test_the_bridge_is_a_compose_service_under_its_own_profile():
    from pathlib import Path
    compose = (Path(__file__).resolve().parents[3] / "docker-compose.prod.yml").read_text()
    assert "jackson:" in compose and 'profiles: ["sso"]' in compose and "boxyhq/jackson" in compose
