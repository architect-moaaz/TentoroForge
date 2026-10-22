"""Where a published application runs: a default per organisation, a choice
per application in the Publish dialog until its first publish fixes it, and
the default — Neon's us-east-2 and Vercel's own region — for everything that
was already published (2026-10-22)."""
from __future__ import annotations

import uuid

import pytest

from services.deploy import regions
from tests.deploy.test_test_and_production import _neon, _publish, _quiet, _vercel  # noqa: F401 — _quiet is autouse
from tests.deploy.test_vercel_provider import _mk_app_tree, db_session, sample_project_id  # noqa: F401


def test_the_default_is_what_every_app_had_before():
    d = regions.get(regions.DEFAULT)
    assert (d["neon"], d["vercel"]) == ("aws-us-east-2", None)


def test_every_choice_pairs_a_neon_region_with_a_vercel_one():
    for rid, r in regions.REGIONS.items():
        assert r["neon"].startswith("aws-")
        assert rid == regions.DEFAULT or (r["vercel"] and len(r["vercel"]) == 4)
    assert "mumbai" not in " ".join(r["label"].lower() for r in regions.REGIONS.values()), "Neon has no Mumbai"


def test_an_apps_own_choice_wins_until_it_is_published():
    org = {"deploy_region": "ap-singapore"}
    assert regions.choose(locked=False, app_choice=None, org_settings=org) == "ap-singapore"
    assert regions.choose(locked=False, app_choice="eu-london", org_settings=org) == "eu-london"
    assert regions.choose(locked=False, app_choice=None, org_settings={}) == regions.DEFAULT


def test_a_published_app_stays_where_it_is():
    org = {"deploy_region": "ap-singapore"}
    assert regions.choose(locked=True, app_choice=None, org_settings=org) == regions.DEFAULT, \
        "published before regions: the default, whatever the organisation picks now"
    assert regions.choose(locked=True, app_choice="eu-london", org_settings=org) == "eu-london"


def test_an_unknown_region_is_refused():
    with pytest.raises(ValueError):
        regions.normalise("ap-mumbai")


@pytest.mark.asyncio
async def test_a_new_database_is_made_in_the_region_and_the_server_beside_it(db_session, sample_project_id, tmp_path):
    _mk_app_tree(tmp_path)
    vercel, neon = _vercel(), _neon(created=True)
    events = await _publish(db_session, sample_project_id, tmp_path, vercel, neon, environment="production",
                            neon_region="aws-ap-southeast-1", vercel_region="sin1")
    assert events[-1].stage == "done"
    assert neon.create_project.call_args.kwargs["region_id"] == "aws-ap-southeast-1"
    vercel.set_function_region.assert_awaited_once()
    assert vercel.set_function_region.call_args.args[1] == "sin1"


@pytest.mark.asyncio
async def test_the_default_leaves_vercel_as_it_is(db_session, sample_project_id, tmp_path):
    _mk_app_tree(tmp_path)
    vercel, neon = _vercel(), _neon(created=True)
    await _publish(db_session, sample_project_id, tmp_path, vercel, neon, environment="production")
    assert neon.create_project.call_args.kwargs["region_id"] == "aws-us-east-2"
    vercel.set_function_region.assert_not_awaited()


# --- the endpoints --------------------------------------------------------------

async def _project_with_output(auth_client, org_id: str, tmp_path) -> str:
    made = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Ledger"})).json()
    from database import async_session
    from models.project import Project
    from services.features import set_feature
    async with async_session() as db:
        # Publishing is off for an organisation until it is switched on.
        from sqlalchemy import select
        from models.auth import PlatformUser
        me = (await db.execute(select(PlatformUser).where(PlatformUser.email == "test@example.com"))).scalar_one()
        await set_feature(db, scope_kind="org", scope_id=org_id, key="publish", enabled=True,
                          reason="the test publishes", by=me)
        await db.commit()
        p = await db.get(Project, uuid.UUID(made["id"]))
        p.output_dir = str(tmp_path / "out")
        await db.commit()
    (tmp_path / "out").mkdir()
    return made["id"]


@pytest.mark.asyncio
async def test_an_organisation_sets_its_default_and_an_app_its_own(test_db, auth_client, org_id, tmp_path):
    got = (await auth_client.get(f"/api/orgs/{org_id}/deploy-region")).json()
    assert got["region"] == regions.DEFAULT and any(r["id"] == "ap-singapore" for r in got["regions"])
    put = await auth_client.put(f"/api/orgs/{org_id}/deploy-region", json={"region": "ap-singapore"})
    assert put.status_code == 200 and put.json()["region"] == "ap-singapore"
    assert (await auth_client.put(f"/api/orgs/{org_id}/deploy-region", json={"region": "mars"})).status_code == 400

    pid = await _project_with_output(auth_client, org_id, tmp_path)
    status = (await auth_client.get(f"/api/projects/{pid}/publish-status")).json()["region"]
    assert (status["region"], status["locked"], status["org_default"]) == ("ap-singapore", False, "ap-singapore")
    mine = await auth_client.put(f"/api/projects/{pid}/deploy-region", json={"region": "eu-london"})
    assert mine.status_code == 200 and mine.json()["region"] == "eu-london"


@pytest.mark.asyncio
async def test_once_its_database_exists_an_app_cannot_be_moved(test_db, auth_client, org_id, tmp_path):
    pid = await _project_with_output(auth_client, org_id, tmp_path)
    from database import async_session
    from models.deployment import Deployment
    async with async_session() as db:
        db.add(Deployment(project_id=uuid.UUID(pid), target="vercel", status="succeeded", environment="production",
                          neon_project_id="np_1"))
        await db.commit()
    status = (await auth_client.get(f"/api/projects/{pid}/publish-status")).json()["region"]
    assert (status["region"], status["locked"]) == (regions.DEFAULT, True), "published before: the default"
    moved = await auth_client.put(f"/api/projects/{pid}/deploy-region", json={"region": "ap-sydney"})
    assert moved.status_code == 409
    same = await auth_client.put(f"/api/projects/{pid}/deploy-region", json={"region": regions.DEFAULT})
    assert same.status_code == 200
