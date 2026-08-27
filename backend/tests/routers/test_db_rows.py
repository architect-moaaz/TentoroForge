"""Tests for the data viewer rows endpoint."""
import pytest
from routers.data_model import build_rows_query


def test_builds_query_with_ascending_sort():
    sql, params = build_rows_query("leave_requests", {"id", "created_at"}, "created_at", "asc", 50, 0)
    assert sql == 'SELECT * FROM "leave_requests" ORDER BY "created_at" ASC LIMIT $1 OFFSET $2'
    assert params == [50, 0]


def test_builds_query_with_descending_sort():
    sql, _ = build_rows_query("t", {"c"}, "c", "desc", 25, 25)
    assert sql == 'SELECT * FROM "t" ORDER BY "c" DESC LIMIT $1 OFFSET $2'


def test_unknown_direction_defaults_to_ascending():
    sql, _ = build_rows_query("t", {"c"}, "c", "sideways", 10, 0)
    assert 'ORDER BY "c" ASC' in sql


def test_no_sort_omits_order_by():
    sql, params = build_rows_query("t", {"c"}, None, "asc", 10, 0)
    assert sql == 'SELECT * FROM "t" LIMIT $1 OFFSET $2'
    assert params == [10, 0]


def test_rejects_sort_column_not_in_table():
    with pytest.raises(ValueError):
        build_rows_query("t", {"id"}, "id; DROP TABLE users", "asc", 10, 0)


import pytest


@pytest.mark.asyncio
async def test_db_rows_requires_admin(auth_client, org_id):
    # auth_client is the org OWNER (created the org) → passes the admin gate.
    proj = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "DV Test"})
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    # Owner: gate passes; no preview running → 400 (NOT 403).
    res = await auth_client.get(f"/api/projects/{project_id}/db/rows?table=anything")
    assert res.status_code == 400, res.text  # "Start preview to view data"

    # A different user who is NOT a member of the org → 403.
    from httpx import ASGITransport, AsyncClient
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as outsider:
        signup = await outsider.post("/api/auth/signup", json={
            "email": "outsider@example.com", "name": "Out", "password": "Testpass123",
        })
        assert signup.status_code == 201, signup.text
        outsider.headers["Authorization"] = f"Bearer {signup.json()['access_token']}"
        res2 = await outsider.get(f"/api/projects/{project_id}/db/rows?table=anything")
        assert res2.status_code == 403, res2.text


@pytest.mark.asyncio
async def test_db_seed_requires_admin(auth_client, org_id):
    # /db/seed writes data — it must be admin-gated like the rest of the data path.
    proj = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "DV Seed Test"})
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    from httpx import ASGITransport, AsyncClient
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as outsider:
        signup = await outsider.post("/api/auth/signup", json={
            "email": "seedoutsider@example.com", "name": "Out2", "password": "Testpass123",
        })
        assert signup.status_code == 201, signup.text
        outsider.headers["Authorization"] = f"Bearer {signup.json()['access_token']}"
        res = await outsider.post(f"/api/projects/{project_id}/db/seed", json={})
        assert res.status_code == 403, res.text
