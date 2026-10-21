"""The addresses a published app answers at — the Domains section of App
settings and the Custom domain card of the Publish dialog both read and
change them here (`services.deploy.domains`)."""
from __future__ import annotations

import logging
import os
import uuid

from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import Project
from services.features import feature_gate
from services.project_service import get_project_with_auth

logger = logging.getLogger(__name__)
router = APIRouter()
#: Changing where an app answers is part of publishing it: the same switch.
_PUBLISH = [Depends(feature_gate("publish"))]


class AddDomain(BaseModel):
    name: str


class OldAddress(BaseModel):
    mode: str


class WriteRecords(BaseModel):
    replace: bool = False


async def _project(project_id: uuid.UUID, user: PlatformUser, db: AsyncSession) -> Project:
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(400, "This app has not been built yet; build it, then give it an address.")
    return project


def _client():
    if not os.environ.get("VERCEL_TOKEN"):
        raise HTTPException(503, "Publishing is not set up on this platform, so addresses cannot be attached.")
    from services.deploy.vercel_client import VercelClient
    return VercelClient()


async def _tell(project_id: uuid.UUID, said: list[str]) -> None:
    """What the domain service said, into the app's chat."""
    if not said:
        return
    try:
        from database import async_session
        from models.project import Conversation, MessageRole, MessageType
        async with async_session() as sess:
            for text in said:
                sess.add(Conversation(project_id=project_id, role=MessageRole.assistant, content=text,
                                      message_type=MessageType.chat, metadata_={"source": "domains"}))
            await sess.commit()
    except Exception:  # noqa: BLE001 — telling is best-effort
        logger.warning("[domains] could not post to the chat of %s", project_id, exc_info=True)


async def _run(project_id: uuid.UUID, user: PlatformUser, db: AsyncSession, act, *, dns: bool = False):
    from services.deploy import dns_accounts
    from services.deploy.domains import DomainRefused, DomainService, project_root, vercel_project_name
    project = await _project(project_id, user, db)
    said: list[str] = []
    client = _client()
    providers = await dns_accounts.load(project.org_id, db) if dns else []
    try:
        from services.deploy.domain_check import check_address
        svc = DomainService(output_dir=str(project_root(project.output_dir)), client=client,
                            project_name=vercel_project_name(project.short_id), say=said.append,
                            address_check=check_address, dns=providers,
                            dns_labels=await dns_accounts.connected_labels(project.org_id, db))
        result = await act(svc)
        return result if result is not None else svc.view()
    except DomainRefused as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(400, "This app has no definition yet.") from exc
    finally:
        await client.close()
        await dns_accounts.close_all(providers)
        await _tell(project_id, said)


@router.get("/api/projects/{project_id}/domains")
async def list_domains(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """The app's addresses, their records and status. Reading never calls
    Vercel; Check now does."""
    from services.deploy import dns_accounts
    from services.deploy.domains import DomainService, project_root, vercel_project_name
    project = await _project(project_id, user, db)
    svc = DomainService(output_dir=str(project_root(project.output_dir)), client=None,
                        project_name=vercel_project_name(project.short_id),
                        dns_labels=await dns_accounts.connected_labels(project.org_id, db))
    return svc.view()


@router.get("/api/projects/{project_id}/domains/updating")
async def domains_updating(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    """How the republish a change of main address started is going (asks
    Vercel), with the addresses as they stand."""
    async def act(svc):
        await svc.check_updating()
        return svc.view()
    return await _run(project_id, user, db, act)


@router.post("/api/projects/{project_id}/domains", dependencies=_PUBLISH)
async def add_domain(project_id: uuid.UUID, body: AddDomain, user: PlatformUser = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    async def act(svc):
        await svc.connect(body.name)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.post("/api/projects/{project_id}/domains/{name}/check", dependencies=_PUBLISH)
async def check_domain(project_id: uuid.UUID, name: str, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    async def act(svc):
        await svc.refresh(name)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.post("/api/projects/{project_id}/domains/{name}/main", dependencies=_PUBLISH)
async def make_main(project_id: uuid.UUID, name: str, user: PlatformUser = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    async def act(svc):
        await svc.make_main(name)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.delete("/api/projects/{project_id}/domains/{name}", dependencies=_PUBLISH)
async def remove_domain(project_id: uuid.UUID, name: str, user: PlatformUser = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    async def act(svc):
        await svc.remove(name)
        return svc.view()
    return await _run(project_id, user, db, act, dns=True)


@router.put("/api/projects/{project_id}/domains/old-address", dependencies=_PUBLISH)
async def set_old_address(project_id: uuid.UUID, body: OldAddress, user: PlatformUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    async def act(svc):
        await svc.set_old_address(body.mode)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.put("/api/projects/{project_id}/domains/tentoro", dependencies=_PUBLISH)
async def rename_tentoro(project_id: uuid.UUID, body: AddDomain, user: PlatformUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Give the app's Tentoro address another name (`aqua`)."""
    async def act(svc):
        await svc.rename_tentoro(body.name)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.post("/api/projects/{project_id}/domains/{name}/records", dependencies=_PUBLISH)
async def write_records(project_id: uuid.UUID, name: str, body: WriteRecords,
                        user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Add the address's records at the organisation's connected DNS account.
    `result` says what was written, or what is in the way."""
    async def act(svc):
        result = await svc.write_records(name, replace=body.replace)
        return {**svc.view(), "result": result}
    return await _run(project_id, user, db, act, dns=True)


@router.post("/api/projects/{project_id}/domains/organisations", dependencies=_PUBLISH)
async def connect_organisations(project_id: uuid.UUID, body: AddDomain, user: PlatformUser = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    """Each organisation of the app answers at its own address under this domain."""
    async def act(svc):
        await svc.connect_organisations(body.name)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.put("/api/projects/{project_id}/domains/organisations/sign-in", dependencies=_PUBLISH)
async def set_organisation_sign_in(project_id: uuid.UUID, body: OldAddress, user: PlatformUser = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_db)):
    """`shared`: one sign-in across the organisations' addresses; `per_organisation`: one at each."""
    async def act(svc):
        await svc.set_organisation_sign_in(body.mode)
        return svc.view()
    return await _run(project_id, user, db, act)


def _return_to(request: Request, project: Project, name: str) -> str:
    """Where the owner lands after approving at their provider: this app's
    Domains settings, on the platform's own address (never one the caller
    names), told which address to check."""
    base = (os.environ.get("FORGE_APP_BASE_URL") or os.environ.get("FORGE_PUBLIC_URL") or "").rstrip("/")
    if not base:
        origin = request.headers.get("origin") or ""
        if urlsplit(origin).scheme in ("http", "https") and urlsplit(origin).netloc:
            base = origin.rstrip("/")
    if not base:
        raise HTTPException(503, "The platform's own address is not known (FORGE_PUBLIC_URL), so the provider "
                                 "would have nowhere to send the owner back to.")
    return f"{base}/org/{project.org_id}/projects/{project.id}?settings=domains&dc={quote(name, safe='')}"


@router.post("/api/projects/{project_id}/domains/{name}/connect", dependencies=_PUBLISH)
async def connect_with_provider(project_id: uuid.UUID, name: str, request: Request,
                                user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The signed Domain Connect link: the owner approves the records at their
    own DNS provider and comes back. `{url, provider}`."""
    project = await _project(project_id, user, db)
    back = _return_to(request, project, name)

    async def act(svc):
        return await svc.connect_url(name, back)
    return await _run(project_id, user, db, act)
