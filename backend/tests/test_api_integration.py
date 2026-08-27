"""Integration tests for the Tentoro Forge API.

Tests the full request → response pipeline through FastAPI,
covering auth, org management, project CRUD, and monitoring endpoints.
"""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_signup_and_login(client: AsyncClient):
    """New user can sign up and then log in."""
    resp = await client.post("/api/auth/signup", json={
        "email": "alice@example.com",
        "name": "Alice",
        "password": "secret123",
    })
    assert resp.status_code == 201
    assert "access_token" in resp.json()

    resp = await client.post("/api/auth/login", json={
        "email": "alice@example.com",
        "password": "secret123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_duplicate_signup(client: AsyncClient):
    """Duplicate email should fail with 409."""
    payload = {
        "email": "dup@example.com",
        "name": "Dup",
        "password": "pass1234",
    }
    await client.post("/api/auth/signup", json=payload)
    resp = await client.post("/api/auth/signup", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """Wrong password should fail with 401."""
    await client.post("/api/auth/signup", json={
        "email": "wrongpw@example.com",
        "name": "Wrong",
        "password": "correct",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "wrongpw@example.com",
        "password": "incorrect",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_endpoint(auth_client: AsyncClient):
    """Authenticated user can access /me."""
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert data["name"] == "Test User"


@pytest.mark.asyncio
async def test_me_without_auth(client: AsyncClient):
    """Unauthenticated request to /me should fail."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Organization CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_org(auth_client: AsyncClient):
    """Create an organization."""
    resp = await auth_client.post("/api/orgs", json={
        "name": "Acme Corp",
        "slug": "acme-corp",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["name"] == "Acme Corp"
    assert data["slug"] == "acme-corp"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_orgs(auth_client: AsyncClient):
    """List organizations for the authenticated user."""
    # Create one first
    await auth_client.post("/api/orgs", json={
        "name": "ListOrg",
        "slug": "list-org",
    })
    resp = await auth_client.get("/api/orgs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_project(auth_client: AsyncClient, org_id: str):
    """Create a project within an org."""
    resp = await auth_client.post(f"/api/orgs/{org_id}/projects", json={
        "name": "Test Project",
        "description": "A test project for integration testing",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["name"] == "Test Project"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_projects(auth_client: AsyncClient, org_id: str):
    """List projects in an org."""
    await auth_client.post(f"/api/orgs/{org_id}/projects", json={
        "name": "Project For List",
    })
    resp = await auth_client.get(f"/api/orgs/{org_id}/projects")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_get_project(auth_client: AsyncClient, org_id: str):
    """Get a single project."""
    create_resp = await auth_client.post(f"/api/orgs/{org_id}/projects", json={
        "name": "GetMe",
    })
    project_id = create_resp.json()["id"]

    resp = await auth_client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "GetMe"


@pytest.mark.asyncio
async def test_update_project(auth_client: AsyncClient, org_id: str):
    """Update a project's name."""
    create_resp = await auth_client.post(f"/api/orgs/{org_id}/projects", json={
        "name": "OldName",
    })
    project_id = create_resp.json()["id"]

    resp = await auth_client.put(f"/api/projects/{project_id}", json={
        "name": "NewName",
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "NewName"


# ---------------------------------------------------------------------------
# Monitoring (Cost Tracking & Errors)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_monitoring_costs(auth_client: AsyncClient, org_id: str):
    """Monitoring costs endpoint returns valid structure."""
    create_resp = await auth_client.post(f"/api/orgs/{org_id}/projects", json={
        "name": "MonitorProject",
    })
    project_id = create_resp.json()["id"]

    resp = await auth_client.get(f"/api/projects/{project_id}/monitoring/costs")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_cost_usd" in data
    assert "total_input_tokens" in data
    assert "total_output_tokens" in data


@pytest.mark.asyncio
async def test_monitoring_errors(auth_client: AsyncClient, org_id: str):
    """Monitoring errors endpoint returns valid structure."""
    create_resp = await auth_client.post(f"/api/orgs/{org_id}/projects", json={
        "name": "ErrorProject",
    })
    project_id = create_resp.json()["id"]

    resp = await auth_client.get(f"/api/projects/{project_id}/monitoring/errors")
    assert resp.status_code == 200
    data = resp.json()
    assert "errors" in data
    assert "total" in data


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_versions(auth_client: AsyncClient, org_id: str):
    """Versions endpoint returns list."""
    create_resp = await auth_client.post(f"/api/orgs/{org_id}/projects", json={
        "name": "VersionProject",
    })
    project_id = create_resp.json()["id"]

    resp = await auth_client.get(f"/api/projects/{project_id}/versions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_conversations(auth_client: AsyncClient, org_id: str):
    """Conversations endpoint returns list."""
    create_resp = await auth_client.post(f"/api/orgs/{org_id}/projects", json={
        "name": "ConvProject",
    })
    project_id = create_resp.json()["id"]

    resp = await auth_client.get(f"/api/projects/{project_id}/conversations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
