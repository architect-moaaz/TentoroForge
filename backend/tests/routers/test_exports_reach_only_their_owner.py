"""A file Smith wrote for one owner reaches that owner and nobody else.

The records an application holds are the customer's data. Everything about the
way they travel has to make crossing a project impossible rather than merely
forbidden, so the route is pinned here: the directory read is the one on the
authorised project's row, the id in the url names a file inside it and nothing
else, and someone outside the org gets the same answer whether or not the file
exists.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from services import project_exports


async def _project(client, org_id, name: str) -> dict:
    """A project, plus the directory the router will read exports out of.

    Derived exactly as `project_service.create_project` derives it — the test
    must not be told the path by the thing it is testing.
    """
    from services.project_service import OUTPUT_BASE

    res = await client.post(f"/api/orgs/{org_id}/projects", json={"name": name})
    assert res.status_code == 201, res.text
    body = res.json()
    return {**body, "output_dir": str(OUTPUT_BASE / body["short_id"])}


@pytest.mark.asyncio
async def test_the_owner_gets_the_file_under_the_name_they_were_shown(auth_client, org_id):
    project = await _project(auth_client, org_id, "Export A")
    rec = project_exports.save_export(
        project["output_dir"], "nurses.csv", b"id,fullName\nn1,Ada\n", "text/csv")

    res = await auth_client.get(f"/api/projects/{project['id']}/exports/{rec['id']}")
    assert res.status_code == 200, res.text
    assert res.content == b"id,fullName\nn1,Ada\n"
    assert res.headers["content-type"].startswith("text/csv")
    assert 'filename="nurses.csv"' in res.headers["content-disposition"]


@pytest.mark.asyncio
async def test_one_project_cannot_address_anothers_export(auth_client, org_id):
    """The id is the only thing the caller supplies, and it does not choose a
    directory — the authorised project's `output_dir` does."""
    mine = await _project(auth_client, org_id, "Export Mine")
    theirs = await _project(auth_client, org_id, "Export Theirs")
    rec = project_exports.save_export(theirs["output_dir"], "theirs.csv", b"x\n", "text/csv")

    res = await auth_client.get(f"/api/projects/{mine['id']}/exports/{rec['id']}")
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_a_traversing_id_is_a_404_not_a_file(auth_client, org_id):
    project = await _project(auth_client, org_id, "Export Traverse")
    res = await auth_client.get(
        f"/api/projects/{project['id']}/exports/..%2F..%2F..%2Fetc%2Fpasswd")
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_somebody_outside_the_org_is_refused_before_the_file_is_looked_for(
        auth_client, org_id):
    project = await _project(auth_client, org_id, "Export Private")
    rec = project_exports.save_export(
        project["output_dir"], "records.csv", b"id\n1\n", "text/csv")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as outsider:
        signup = await outsider.post("/api/auth/signup", json={
            "email": "notyours@example.com", "name": "Out", "password": "Testpass123",
        })
        assert signup.status_code == 201, signup.text
        outsider.headers["Authorization"] = f"Bearer {signup.json()['access_token']}"
        res = await outsider.get(f"/api/projects/{project['id']}/exports/{rec['id']}")
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_an_unauthenticated_request_gets_nothing(auth_client, org_id):
    project = await _project(auth_client, org_id, "Export Anon")
    rec = project_exports.save_export(project["output_dir"], "r.csv", b"id\n", "text/csv")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anon:
        res = await anon.get(f"/api/projects/{project['id']}/exports/{rec['id']}")
    assert res.status_code in (401, 403), res.text
