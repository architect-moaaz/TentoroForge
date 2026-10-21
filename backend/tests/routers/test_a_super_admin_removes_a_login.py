"""The super admin removes a login for good, with its email typed back.

`projects.owner_id` cascades in the database, so removing the row as it
stands would have deleted every app the person made. Each app is handed to
another owner (else an admin) of its organisation first; an organisation the
person alone owns refuses the removal until its ownership moves or it is
purged; and what the person did stays on the record."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


async def _fresh():
    from main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _person_id(admin, email: str) -> str:
    items = (await admin.get("/api/admin/people", params={"q": email})).json()["items"]
    return next(p["id"] for p in items if p["email"] == email)


@pytest.mark.asyncio
async def test_a_login_is_removed_and_its_apps_stay_with_the_organisation(auth_client, super_admin_client, org_id):
    # Ann co-owns the organisation and made an app in it.
    async with await _fresh() as ann:
        r = await ann.post("/api/auth/signup", json={"email": "ann@example.com", "name": "Ann", "password": "Testpass123"})
        ann.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        r = await super_admin_client.post(f"/api/admin/orgs/{org_id}/members", json={"email": "ann@example.com", "role": "owner"})
        assert r.status_code == 201, r.text
        made = await ann.post(f"/api/orgs/{org_id}/projects", json={"name": "Ann's app"})
        assert made.status_code in (200, 201), made.text
        project_id = made.json()["id"]
        ann_id = await _person_id(super_admin_client, "ann@example.com")

        # The email must be typed back exactly.
        r = await super_admin_client.post(f"/api/admin/people/{ann_id}/delete", json={"confirm_email": "ann@example"})
        assert r.status_code == 400

        r = await super_admin_client.post(f"/api/admin/people/{ann_id}/delete", json={"confirm_email": "Ann@Example.com"})
        assert r.status_code == 200, r.text
        assert r.json() == {"deleted": True, "email": "ann@example.com", "apps_handed_on": 1, "organisations_left": 1}

        # Her session is over, and she is gone from the cockpit.
        assert (await ann.get("/api/auth/me")).status_code == 401
    items = (await super_admin_client.get("/api/admin/people", params={"q": "ann@example.com"})).json()["items"]
    assert items == []

    # The app is still there, now the remaining owner's.
    r = await auth_client.get(f"/api/orgs/{org_id}/projects")
    assert project_id in {p["id"] for p in (r.json() if isinstance(r.json(), list) else r.json().get("items", []))}

    # And the removal is on the record.
    rows = (await super_admin_client.get("/api/admin/audit", params={"action": "person.delete"})).json()
    assert rows and rows[0]["changes"]["email"] == "ann@example.com" and len(rows[0]["changes"]["apps_handed_on"]) == 1


@pytest.mark.asyncio
async def test_the_only_owner_of_an_organisation_is_not_removed(auth_client, super_admin_client, org_id):
    tid = await _person_id(super_admin_client, "test@example.com")
    r = await super_admin_client.post(f"/api/admin/people/{tid}/delete", json={"confirm_email": "test@example.com"})
    assert r.status_code == 409
    assert "only owner of Test Org" in r.json()["detail"] and "Transfer ownership or purge" in r.json()["detail"]
    assert (await auth_client.get("/api/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_a_super_admin_cannot_remove_themself_or_another_super_admin(auth_client, super_admin_client):
    me = await _person_id(super_admin_client, "admin@tentoro.ai")
    r = await super_admin_client.post(f"/api/admin/people/{me}/delete", json={"confirm_email": "admin@tentoro.ai"})
    assert r.status_code == 400
    other = await _person_id(super_admin_client, "test@example.com")
    assert (await super_admin_client.post(f"/api/admin/people/{other}/super-admin")).status_code == 200
    r = await super_admin_client.post(f"/api/admin/people/{other}/delete", json={"confirm_email": "test@example.com"})
    assert r.status_code == 409 and "revoke the role first" in r.json()["detail"]


@pytest.mark.asyncio
async def test_only_a_super_admin_may_remove_a_login(auth_client, super_admin_client):
    ann = await _fresh()
    r = await ann.post("/api/auth/signup", json={"email": "ann2@example.com", "name": "Ann", "password": "Testpass123"})
    aid = await _person_id(super_admin_client, "ann2@example.com")
    r = await auth_client.post(f"/api/admin/people/{aid}/delete", json={"confirm_email": "ann2@example.com"})
    assert r.status_code == 403
    await ann.aclose()
