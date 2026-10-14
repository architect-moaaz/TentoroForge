"""The editor and debug routes served any folder under output/ to anyone who
knew its name — the IR and design editors, the file reads and writes, a
Smith turn, a publish. Each now wants a signed-in member of the project's
organisation: 401 with no token, 403 as a stranger, through as a member."""
from __future__ import annotations

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def project(auth_client, org_id):
    r = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Guarded App"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest_asyncio.fixture
async def stranger(client):
    r = await client.post("/api/auth/signup", json={"email": "stranger@example.com", "name": "S", "password": "Stranger123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _routes(project: dict) -> list[tuple[str, str, dict | None]]:
    pid, sid = project["id"], project["short_id"]
    return [
        ("get", f"/api/projects/{pid}/schemas", None),
        ("get", f"/api/projects/{sid}/theme", None),
        ("post", f"/api/projects/{pid}/smith/warmup", None),
        ("get", f"/api/projects/{pid}/ir", None),
        ("get", f"/api/projects/{pid}/design", None),
        ("get", f"/api/_debug/project-file/{sid}/package.json", None),
        ("get", f"/api/_debug/fidelity-log/{sid}", None),
        ("post", f"/api/projects/{pid}/publish", {}),
    ]


@pytest.mark.asyncio
async def test_without_a_token_every_route_is_401(project):
    # A client of its own: the shared one carries the member's token.
    from httpx import ASGITransport, AsyncClient
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as nobody:
        for method, path, body in _routes(project):
            r = await getattr(nobody, method)(path, json=body) if body is not None else await getattr(nobody, method)(path)
            assert r.status_code in (401, 403), (path, r.status_code)
            assert r.status_code == 401 or "Not authenticated" in r.text, (path, r.text)


@pytest.mark.asyncio
async def test_a_stranger_is_403_and_a_member_is_through(client, auth_client, project, stranger):
    for method, path, body in _routes(project):
        r = await getattr(client, method)(path, json=body, headers=stranger) if body is not None \
            else await getattr(client, method)(path, headers=stranger)
        assert r.status_code == 403, (path, r.status_code, r.text)
    # A member reaches the route itself; whatever it answers about a bare
    # project, it is not a refusal.
    for method, path, body in _routes(project):
        if "publish" in path:
            continue
        r = await getattr(auth_client, method)(path, json=body) if body is not None else await getattr(auth_client, method)(path)
        assert r.status_code not in (401, 403), (path, r.status_code, r.text)


@pytest.mark.asyncio
async def test_a_folder_with_no_row_and_the_folder_listing_are_closed(auth_client, super_admin_client):
    assert (await auth_client.get("/api/projects/nosuchid/schemas")).status_code == 404
    assert (await auth_client.get("/api/projects")).status_code == 403
    assert (await super_admin_client.get("/api/projects")).status_code == 200
    assert (await super_admin_client.get("/api/_debug/fidelity-stats")).status_code in (200, 404, 503)
    assert (await auth_client.get("/api/_debug/fidelity-stats")).status_code == 403
