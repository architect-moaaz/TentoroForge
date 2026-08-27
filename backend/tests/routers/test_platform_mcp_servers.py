"""Tests for /api/orgs/{org_id}/mcp-servers CRUD + tools/test endpoints.

We do NOT hit a real MCP server in these tests — `mcp_client.list_tools`
and `mcp_client.probe` are patched. The goal is coverage of:
  * admin auth gate,
  * secret round-trip through platform_integrations_crypto,
  * response shape never includes plaintext secrets,
  * PATCH clear-secret semantics,
  * tools/test endpoints delegate to mcp_client and surface errors sanely.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Ensure every model is imported into Base.metadata before the test_db
# fixture calls create_all — otherwise auth's platform_users table (and
# our platform_mcp_servers) won't exist in the in-memory SQLite.
import models  # noqa: F401  (side-effect import)


@pytest.fixture(autouse=True)
def _master_secret(monkeypatch):
    monkeypatch.setenv(
        "FORGE_INTEGRATIONS_SECRET",
        "test-master-secret-that-is-long-enough-1234567890",
    )


# --------------------------------------------------------------------------- #
# CRUD happy path
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_create_and_list_hides_secret(auth_client, org_id):
    r = await auth_client.post(
        f"/api/orgs/{org_id}/mcp-servers",
        json={
            "name": "Firecrawl",
            "server_url": "https://mcp.firecrawl.dev/v1",
            "transport": "http",
            "auth_kind": "bearer",
            "auth_secret": "fc-secret-abc",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Firecrawl"
    assert body["auth_kind"] == "bearer"
    assert body["has_auth"] is True
    # Never leak the secret in any shape.
    assert "auth_secret" not in body
    assert "auth_secret_ct" not in body
    assert "fc-secret-abc" not in r.text

    listed = await auth_client.get(f"/api/orgs/{org_id}/mcp-servers")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["has_auth"] is True
    assert "auth_secret" not in rows[0]


@pytest.mark.asyncio
async def test_secret_round_trips_through_db(auth_client, org_id):
    """Create → decrypt directly from the DB row and verify plaintext survives."""
    r = await auth_client.post(
        f"/api/orgs/{org_id}/mcp-servers",
        json={
            "name": "X", "server_url": "https://x", "transport": "http",
            "auth_kind": "bearer", "auth_secret": "tok_round_trip_123",
        },
    )
    assert r.status_code == 201, r.text
    server_id = r.json()["id"]

    # Peek into DB and decrypt.
    from database import get_db
    from models.platform_mcp_server import PlatformMcpServer
    from services.platform_integrations_crypto import decrypt
    from sqlalchemy import select
    import uuid as _uuid

    async for db in get_db():
        res = await db.execute(
            select(PlatformMcpServer).where(PlatformMcpServer.id == _uuid.UUID(server_id))
        )
        row = res.scalar_one()
        plaintext = decrypt("mcp", row.auth_secret_ct, row.auth_secret_iv)
        assert plaintext == "tok_round_trip_123"
        break


@pytest.mark.asyncio
async def test_patch_clears_secret_with_empty_string(auth_client, org_id):
    r = await auth_client.post(
        f"/api/orgs/{org_id}/mcp-servers",
        json={
            "name": "Y", "server_url": "https://y", "transport": "http",
            "auth_kind": "bearer", "auth_secret": "before",
        },
    )
    server_id = r.json()["id"]

    # Clearing the secret must be paired with switching auth_kind to 'none' —
    # otherwise the post-condition rejects it.
    upd = await auth_client.patch(
        f"/api/orgs/{org_id}/mcp-servers/{server_id}",
        json={"auth_kind": "none", "auth_secret": ""},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["has_auth"] is False
    assert upd.json()["auth_kind"] == "none"


@pytest.mark.asyncio
async def test_patch_updates_name_without_touching_secret(auth_client, org_id):
    r = await auth_client.post(
        f"/api/orgs/{org_id}/mcp-servers",
        json={
            "name": "Z", "server_url": "https://z", "transport": "http",
            "auth_kind": "bearer", "auth_secret": "keep",
        },
    )
    server_id = r.json()["id"]

    upd = await auth_client.patch(
        f"/api/orgs/{org_id}/mcp-servers/{server_id}",
        json={"name": "Z-renamed"},
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "Z-renamed"
    assert upd.json()["has_auth"] is True


@pytest.mark.asyncio
async def test_delete_returns_204(auth_client, org_id):
    r = await auth_client.post(
        f"/api/orgs/{org_id}/mcp-servers",
        json={"name": "D", "server_url": "https://d", "transport": "http", "auth_kind": "none"},
    )
    server_id = r.json()["id"]
    d = await auth_client.delete(f"/api/orgs/{org_id}/mcp-servers/{server_id}")
    assert d.status_code == 204
    listed = await auth_client.get(f"/api/orgs/{org_id}/mcp-servers")
    assert listed.json() == []


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_apikey_header_requires_header_name(auth_client, org_id):
    r = await auth_client.post(
        f"/api/orgs/{org_id}/mcp-servers",
        json={
            "name": "H", "server_url": "https://h", "transport": "http",
            "auth_kind": "apikey_header", "auth_secret": "k",
            # missing auth_header_name
        },
    )
    assert r.status_code == 400
    assert "auth_header_name" in r.text


@pytest.mark.asyncio
async def test_bearer_requires_secret(auth_client, org_id):
    r = await auth_client.post(
        f"/api/orgs/{org_id}/mcp-servers",
        json={
            "name": "B", "server_url": "https://b", "transport": "http",
            "auth_kind": "bearer",
        },
    )
    assert r.status_code == 400
    assert "auth_secret" in r.text


# --------------------------------------------------------------------------- #
# Auth gate
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_unauth_list_rejected(client, org_id):
    """No auth header rejected. (`org_id` fixture depends on `auth_client`
    which mutates the shared client — strip Authorization to simulate
    an unauthenticated caller.)"""
    client.headers.pop("Authorization", None)
    r = await client.get(f"/api/orgs/{org_id}/mcp-servers")
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------- #
# tools + test endpoints (mcp_client is patched)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_tools_endpoint_returns_shape(auth_client, org_id, monkeypatch):
    r = await auth_client.post(
        f"/api/orgs/{org_id}/mcp-servers",
        json={"name": "T", "server_url": "https://t", "transport": "http", "auth_kind": "none"},
    )
    server_id = r.json()["id"]

    from services import mcp_client as mc

    async def fake_list_tools(server, *, use_cache=True):
        return [
            mc.McpTool(name="search", description="Search", input_schema={"type": "object"}),
        ]

    monkeypatch.setattr(mc, "list_tools", fake_list_tools)

    r2 = await auth_client.get(f"/api/orgs/{org_id}/mcp-servers/{server_id}/tools")
    assert r2.status_code == 200, r2.text
    assert r2.json() == [
        {"name": "search", "description": "Search", "input_schema": {"type": "object"}},
    ]


@pytest.mark.asyncio
async def test_tools_endpoint_surfaces_domain_error_as_502(auth_client, org_id, monkeypatch):
    r = await auth_client.post(
        f"/api/orgs/{org_id}/mcp-servers",
        json={"name": "T2", "server_url": "https://t2", "transport": "http", "auth_kind": "none"},
    )
    server_id = r.json()["id"]

    from services import mcp_client as mc

    async def fake_list_tools(server, *, use_cache=True):
        raise mc.McpClientError("unreachable", "boom")

    monkeypatch.setattr(mc, "list_tools", fake_list_tools)

    r2 = await auth_client.get(f"/api/orgs/{org_id}/mcp-servers/{server_id}/tools")
    assert r2.status_code == 502, r2.text
    assert "boom" in r2.text


@pytest.mark.asyncio
async def test_test_endpoint_returns_probe_payload(auth_client, org_id, monkeypatch):
    r = await auth_client.post(
        f"/api/orgs/{org_id}/mcp-servers",
        json={"name": "P", "server_url": "https://p", "transport": "http", "auth_kind": "none"},
    )
    server_id = r.json()["id"]

    from services import mcp_client as mc

    async def fake_probe(server):
        return {"ok": True, "tool_count": 5}

    monkeypatch.setattr(mc, "probe", fake_probe)

    r2 = await auth_client.post(f"/api/orgs/{org_id}/mcp-servers/{server_id}/test")
    assert r2.status_code == 200
    assert r2.json() == {"ok": True, "tool_count": 5, "error": None, "kind": None}
