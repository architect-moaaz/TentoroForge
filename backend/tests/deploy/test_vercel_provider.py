"""Integration test for VercelDeployProvider — full publish flow with
every HTTP call mocked via respx and the async DB from conftest."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from models.deployment import Deployment
from services.deploy.provider import DeploySnapshot
from services.deploy.vercel_provider import VercelDeployProvider


@pytest_asyncio.fixture
async def db_session(test_db):
    """Yield an AsyncSession from the app's engine — same one the
    /publish route will use."""
    from database import async_session

    async with async_session() as s:
        yield s


@pytest_asyncio.fixture
async def sample_project_id(db_session):
    """A project row we can attach deployments to. Uses raw SQL because
    Project has FK to Organization / User which we don't want to seed
    here — the deploy provider only reads project_id as a foreign key."""
    from sqlalchemy import text

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()

    # Seed minimal parent rows so the FK holds
    await db_session.execute(
        text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'x', 'x')"),
        {"id": str(org_id)},
    )
    await db_session.execute(
        text(
            "INSERT INTO platform_users (id, email, name, password_hash) "
            "VALUES (:id, 'a@b.c', 'Test', 'x')"
        ),
        {"id": str(user_id)},
    )
    await db_session.execute(
        text(
            "INSERT INTO projects (id, org_id, owner_id, name, short_id, status) "
            "VALUES (:id, :org, :owner, 'Acme', 'testabcd', 'ready')"
        ),
        {"id": str(project_id), "org": str(org_id), "owner": str(user_id)},
    )
    await db_session.commit()
    return project_id


def _mk_app_tree(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text('{"name":"acme"}', encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "page.tsx").write_text("export default () => null;", encoding="utf-8")
    return tmp_path


def _mock_vercel_client(vercel_url: str = "acme-a1b2.vercel.app") -> Any:
    """Async-mock stand-in for VercelClient so we don't need respx here —
    the client itself is covered by test_vercel_client."""
    m = AsyncMock()
    m.create_project.return_value = {"id": "prj_abc"}
    m.get_or_create_project.return_value = ({"id": "prj_abc"}, True)
    m.set_env.return_value = {"created": []}
    m.list_env.return_value = []
    m.update_env.return_value = None
    m.disable_deployment_protection.return_value = None
    m.upload_file.return_value = None
    m.create_deployment.return_value = {
        "id": "dpl_xyz",
        "url": vercel_url,
    }
    m.get_deployment.return_value = {
        "readyState": "READY",
        "url": vercel_url,
    }
    m.close = AsyncMock()
    return m


def _mock_neon_client() -> Any:
    m = AsyncMock()
    m.create_project.return_value = {
        "project_id": "np_123",
        "database_url": "postgres://user:pass@ep.neon.tech/main",
        "branch_id": "br_1",
    }
    m.close = AsyncMock()
    return m


@pytest.mark.asyncio
async def test_publish_full_flow_first_deploy(
    db_session, sample_project_id, tmp_path, monkeypatch
) -> None:
    """Fresh publish: creates Neon project, creates Vercel project,
    uploads files, polls to READY, writes succeeded row with a URL."""
    _mk_app_tree(tmp_path)

    vercel = _mock_vercel_client()
    neon = _mock_neon_client()

    # Stub the post-READY DB smoke check — the real one HTTP-probes the
    # deployed Vercel URL, which doesn't resolve in tests.
    async def _fake_smoke(url: str):
        return True, None
    monkeypatch.setattr(
        "services.deploy.vercel_provider._smoke_test_db", _fake_smoke,
    )

    provider = VercelDeployProvider(db=db_session, vercel=vercel, neon=neon)
    snap = DeploySnapshot(
        project_id=str(sample_project_id),
        project_slug="acme",
        output_dir=str(tmp_path),
        integrations={"RESEND_API_KEY": "re_1"},
    )

    events = []
    async for e in provider.publish(snap):
        events.append(e)

    stages = [e.stage for e in events]
    assert stages[0] == "snapshot"
    assert "provision_db" in stages
    assert "upload" in stages
    assert "build" in stages
    assert "activate" in stages
    assert stages[-1] == "done"

    final = events[-1]
    assert final.data is not None
    assert final.data["url"].startswith("https://acme-a1b2.vercel.app")

    # Deployment row landed as succeeded
    res = await db_session.execute(
        select(Deployment).where(Deployment.project_id == sample_project_id)
    )
    row = res.scalars().first()
    assert row is not None
    assert row.status == "succeeded"
    assert row.url == "https://acme-a1b2.vercel.app"
    assert row.vercel_project_id == "prj_abc"
    assert row.vercel_deployment_id == "dpl_xyz"
    assert row.neon_project_id == "np_123"

    # Neon was created exactly once, Vercel project resolved exactly once
    assert neon.create_project.call_count == 1
    assert vercel.get_or_create_project.call_count == 1
    # Env vars pushed at least: NODE_ENV / DATABASE_URL / NEXTAUTH_URL /
    # NEXTAUTH_SECRET / RESEND_API_KEY + one final NEXTAUTH_URL re-set
    assert vercel.set_env.call_count >= 5


@pytest.mark.asyncio
async def test_publish_reports_error_on_vercel_error_state(
    db_session, sample_project_id, tmp_path
) -> None:
    _mk_app_tree(tmp_path)

    vercel = _mock_vercel_client()
    vercel.get_deployment.return_value = {"readyState": "ERROR"}
    neon = _mock_neon_client()

    provider = VercelDeployProvider(db=db_session, vercel=vercel, neon=neon)
    snap = DeploySnapshot(
        project_id=str(sample_project_id),
        project_slug="acme",
        output_dir=str(tmp_path),
    )

    events = [e async for e in provider.publish(snap)]
    assert events[-1].stage == "error"
    assert "failed" in events[-1].message.lower()

    res = await db_session.execute(
        select(Deployment).where(Deployment.project_id == sample_project_id)
    )
    row = res.scalars().first()
    assert row.status == "failed"


@pytest.mark.asyncio
async def test_publish_swallows_mid_pipeline_exception(
    db_session, sample_project_id, tmp_path
) -> None:
    """A random exception mid-publish (Neon 500, Vercel 500, network
    blip) must not leak a traceback — it terminates the stream with
    stage=error and marks the Deployment row failed."""
    _mk_app_tree(tmp_path)

    vercel = _mock_vercel_client()
    neon = _mock_neon_client()
    # Fake a Neon outage
    neon.create_project.side_effect = RuntimeError("Neon outage")

    provider = VercelDeployProvider(db=db_session, vercel=vercel, neon=neon)
    snap = DeploySnapshot(
        project_id=str(sample_project_id),
        project_slug="acme",
        output_dir=str(tmp_path),
    )

    events = [e async for e in provider.publish(snap)]
    assert events[-1].stage == "error"
    assert "Neon outage" in events[-1].message

    res = await db_session.execute(
        select(Deployment).where(Deployment.project_id == sample_project_id)
    )
    row = res.scalars().first()
    assert row.status == "failed"
    assert row.error and "Neon outage" in row.error
