"""The template routes: an organisation's templates reach its members and nobody else.

A template is a whole application's definition, so it is as private as the
project it came from. Saving needs access to the project; seeing, using,
renaming and deleting need membership of the template's organisation, and a
template of another organisation answers 404 — the same as one that does not
exist.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from services import project_templates as templates

FIXTURE = Path(__file__).resolve().parents[2] / "fleet" / "blueprints" / "ats-live.json"


async def _defined_project(client, org_id, name: str) -> dict:
    from services.project_service import OUTPUT_BASE

    res = await client.post(f"/api/orgs/{org_id}/projects", json={"name": name})
    assert res.status_code == 201, res.text
    body = res.json()
    out = Path(OUTPUT_BASE) / body["short_id"]
    (out / ".forge" / "blueprint").mkdir(parents=True, exist_ok=True)
    (out / ".forge" / "blueprint" / "current.json").write_text(FIXTURE.read_text())
    return {**body, "output_dir": out}


async def _outsider(email: str) -> AsyncClient:
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    signup = await c.post("/api/auth/signup", json={
        "email": email, "name": "Out", "password": "Testpass123"})
    assert signup.status_code == 201, signup.text
    c.headers["Authorization"] = f"Bearer {signup.json()['access_token']}"
    return c


@pytest.mark.asyncio
async def test_save_list_use_rename_delete(auth_client, org_id):
    src = await _defined_project(auth_client, org_id, "Hiring")
    res = await auth_client.post(f"/api/projects/{src['id']}/templates",
                                 json={"name": "Hiring desk"})
    assert res.status_code == 201, res.text
    tpl = res.json()
    assert tpl["name"] == "Hiring desk" and tpl["can_manage"] is True
    assert tpl["summary"]["counts"]["pages"] > 0

    listed = (await auth_client.get(f"/api/orgs/{org_id}/project-templates")).json()["templates"]
    assert [t["id"] for t in listed] == [tpl["id"]]

    res = await auth_client.post(f"/api/orgs/{org_id}/projects/from-project-template",
                                 json={"template_id": tpl["id"], "name": "Acme Hiring"})
    assert res.status_code == 201, res.text
    new = res.json()
    from services.project_service import OUTPUT_BASE
    new_out = Path(OUTPUT_BASE) / new["short_id"]
    assert templates.pending(new_out)["template_id"] == tpl["id"]
    assert not (new_out / ".forge" / "blueprint" / "current.json").exists()

    # Smith greets with the two choices, before anything is defined.
    greet = (await auth_client.get(f"/api/projects/{new['id']}/smith/greeting")).json()
    assert greet["choices"] == ["The exact same app", "Something like it, but different"]
    assert "Hiring desk" in greet["headline"]

    res = await auth_client.patch(f"/api/project-templates/{tpl['id']}", json={"name": "Hiring v2"})
    assert res.status_code == 200 and res.json()["name"] == "Hiring v2"
    res = await auth_client.delete(f"/api/project-templates/{tpl['id']}")
    assert res.status_code == 204
    assert (await auth_client.get(f"/api/project-templates/{tpl['id']}")).status_code == 404
    # The project made from it keeps its own copy.
    assert (new_out / templates.STAGE_DIR / "blueprint.json").is_file()


@pytest.mark.asyncio
async def test_a_project_with_nothing_defined_cannot_be_a_template(auth_client, org_id):
    res = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Blank"})
    res = await auth_client.post(f"/api/projects/{res.json()['id']}/templates", json={})
    assert res.status_code == 400 and "definition" in res.json()["detail"]


@pytest.mark.asyncio
async def test_another_organisation_sees_nothing_and_can_use_nothing(auth_client, org_id):
    src = await _defined_project(auth_client, org_id, "Private")
    tpl = (await auth_client.post(f"/api/projects/{src['id']}/templates", json={})).json()

    outsider = await _outsider("templates-outsider@example.com")
    try:
        assert (await outsider.get(f"/api/orgs/{org_id}/project-templates")).status_code == 403
        assert (await outsider.get(f"/api/project-templates/{tpl['id']}")).status_code == 404
        assert (await outsider.patch(f"/api/project-templates/{tpl['id']}",
                                     json={"name": "x"})).status_code == 404
        assert (await outsider.delete(f"/api/project-templates/{tpl['id']}")).status_code == 404
        assert (await outsider.post(f"/api/projects/{src['id']}/templates",
                                    json={})).status_code in (403, 404)
        # Their own organisation cannot reach it by id either.
        own = await outsider.post("/api/orgs", json={"name": "Theirs", "slug": "theirs-tpl"})
        res = await outsider.post(f"/api/orgs/{own.json()['id']}/projects/from-project-template",
                                  json={"template_id": tpl["id"], "name": "Stolen"})
        assert res.status_code == 404
        assert not (await outsider.get(
            f"/api/orgs/{own.json()['id']}/project-templates")).json()["templates"]
    finally:
        await outsider.aclose()
    assert templates.get(tpl["id"])["name"] == tpl["name"]


@pytest.mark.asyncio
async def test_a_bad_template_id_is_a_404(auth_client, org_id):
    for bad in ("..%2F..%2Fetc", "nope", "0" * 31):
        assert (await auth_client.get(f"/api/project-templates/{bad}")).status_code == 404
    res = await auth_client.post(f"/api/orgs/{org_id}/projects/from-project-template",
                                 json={"template_id": "../x", "name": "X"})
    assert res.status_code == 404
