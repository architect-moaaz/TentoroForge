"""The company profile an organisation carries, through its own door.

The profile is shared by everyone in the company and it decides how every
application built afterwards looks. So the two things worth holding here are
that reading it is normal and changing it is not, and that a skip is recorded
rather than lost — the whole point of the optional discovery is that Settings
can offer to finish it.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient


READ = {
    "source_url": "https://northwind.test",
    "company_name": "Northwind",
    "logo_path": None,
    "identity": {"who_you_are": "A family bakery.",
                 "what_you_do": "We bake sourdough overnight.",
                 "how_you_do_it": "Long ferments, one bakery."},
    "design": {"colors": {"primary": "#1B7F5A", "background": "#FFFFFF"},
               "typography": {"fontFamilyBase": "Inter"}},
    "evidence": {"rendered": True, "brandFrom": "the background of its buttons (6 elements)"},
    "design_md": "# Northwind — design language\n",
}


@pytest.mark.asyncio
async def test_an_organisation_with_no_profile_says_so_rather_than_404ing(
        auth_client: AsyncClient, org_id: str):
    """"Nobody has run discovery" is a state the onboarding card and the
    Settings tab both render, not an error either has to catch."""
    resp = await auth_client.get(f"/api/orgs/{org_id}/brand")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_a_read_site_becomes_the_profile_and_its_document(
        auth_client: AsyncClient, org_id: str):
    with patch("services.brand_discovery.discover", return_value=dict(READ)):
        resp = await auth_client.post(
            f"/api/orgs/{org_id}/brand/discover",
            json={"url": "https://northwind.test"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ready" and body["usable"] is True
    assert body["company_name"] == "Northwind"
    assert body["design"]["colors"]["primary"] == "#1B7F5A"
    assert body["design_md"].startswith("# Northwind")

    # And it is there on the next read, for everyone in the organisation.
    again = await auth_client.get(f"/api/orgs/{org_id}/brand")
    assert again.json()["company_name"] == "Northwind"


@pytest.mark.asyncio
async def test_a_site_that_cannot_be_read_says_why_and_keeps_the_address(
        auth_client: AsyncClient, org_id: str):
    """A refusal the person can act on, not a server fault — and the URL
    survives so Settings can offer to try it again."""
    from services.brand_discovery import SiteUnreadable

    with patch("services.brand_discovery.discover",
               side_effect=SiteUnreadable("Could not reach that address.")):
        resp = await auth_client.post(
            f"/api/orgs/{org_id}/brand/discover", json={"url": "https://nope.test"})
    assert resp.status_code == 422
    assert "Could not reach" in resp.json()["detail"]

    stored = (await auth_client.get(f"/api/orgs/{org_id}/brand")).json()
    assert stored["status"] == "failed"
    assert stored["source_url"] == "https://nope.test"
    assert "Could not reach" in stored["failure_reason"]
    assert stored["usable"] is False


@pytest.mark.asyncio
async def test_a_correction_regenerates_the_document_in_the_same_call(
        auth_client: AsyncClient, org_id: str):
    """The structure and the document cannot be allowed to disagree: a
    document regenerated later is a document that is wrong in between."""
    with patch("services.brand_discovery.discover", return_value=dict(READ)):
        await auth_client.post(f"/api/orgs/{org_id}/brand/discover",
                               json={"url": "https://northwind.test"})

    resp = await auth_client.put(f"/api/orgs/{org_id}/brand", json={
        "company_name": "Northwind Bakery",
        "design": {"colors": {"primary": "#7C3AED"}},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["design"]["colors"]["primary"] == "#7C3AED"
    assert "#7C3AED" in body["design_md"]
    assert "#1B7F5A" not in body["design_md"]
    assert "Northwind Bakery" in body["design_md"]


@pytest.mark.asyncio
async def test_an_organisation_that_never_had_a_site_can_still_have_a_language(
        auth_client: AsyncClient, org_id: str):
    """`PUT` creates as well as corrects — the profile is not only reachable
    through a URL somebody was able to read."""
    resp = await auth_client.put(f"/api/orgs/{org_id}/brand", json={
        "company_name": "Handmade Ltd",
        "identity": {"what_you_do": "We restore furniture."},
        "design": {"colors": {"primary": "#8B5A2B"}},
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
    assert resp.json()["usable"] is True


@pytest.mark.asyncio
async def test_not_now_is_recorded_so_settings_can_offer_to_finish_it(
        auth_client: AsyncClient, org_id: str):
    resp = await auth_client.post(f"/api/orgs/{org_id}/brand/skip")
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"
    assert resp.json()["usable"] is False


@pytest.mark.asyncio
async def test_skipping_never_destroys_a_language_already_on_record(
        auth_client: AsyncClient, org_id: str):
    """Otherwise a stray click on a card silently deletes the design language
    every future application would have been built in."""
    with patch("services.brand_discovery.discover", return_value=dict(READ)):
        await auth_client.post(f"/api/orgs/{org_id}/brand/discover",
                               json={"url": "https://northwind.test"})
    resp = await auth_client.post(f"/api/orgs/{org_id}/brand/skip")
    assert resp.json()["status"] == "ready"
    assert resp.json()["design"]["colors"]["primary"] == "#1B7F5A"


@pytest.mark.asyncio
async def test_a_stranger_cannot_read_or_change_a_company_s_design_language(
        auth_client: AsyncClient, org_id: str, client: AsyncClient):
    other = await client.post("/api/auth/signup", json={
        "email": "outsider@example.com", "name": "Outsider",
        "password": "Testpass123"})
    assert other.status_code == 201
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    assert (await client.get(f"/api/orgs/{org_id}/brand",
                             headers=headers)).status_code == 403
    assert (await client.put(f"/api/orgs/{org_id}/brand", json={"company_name": "Mine"},
                             headers=headers)).status_code == 403
    assert (await client.post(f"/api/orgs/{org_id}/brand/discover",
                              json={"url": "https://northwind.test"},
                              headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_the_document_can_be_read_as_a_document(
        auth_client: AsyncClient, org_id: str):
    assert (await auth_client.get(
        f"/api/orgs/{org_id}/brand/design.md")).status_code == 404

    with patch("services.brand_discovery.discover", return_value=dict(READ)):
        await auth_client.post(f"/api/orgs/{org_id}/brand/discover",
                               json={"url": "https://northwind.test"})

    resp = await auth_client.get(f"/api/orgs/{org_id}/brand/design.md")
    assert resp.status_code == 200
    assert resp.text.startswith("# Northwind")
    assert resp.headers["content-type"].startswith("text/markdown")
