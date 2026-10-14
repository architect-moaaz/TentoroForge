"""The addresses a published app answers at — the Domains section of App
settings and the Custom domain card of the Publish dialog both read and
change them here (`services.deploy.domains`)."""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import Project
from services.project_service import get_project_with_auth

logger = logging.getLogger(__name__)
router = APIRouter()


class AddDomain(BaseModel):
    name: str


class OldAddress(BaseModel):
    mode: str


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


async def _run(project_id: uuid.UUID, user: PlatformUser, db: AsyncSession, act):
    from services.deploy.domains import DomainRefused, DomainService, project_root, vercel_project_name
    project = await _project(project_id, user, db)
    said: list[str] = []
    client = _client()
    try:
        from services.deploy.domain_check import check_address
        svc = DomainService(output_dir=str(project_root(project.output_dir)), client=client,
                            project_name=vercel_project_name(project.short_id), say=said.append,
                            address_check=check_address)
        result = await act(svc)
        return result if result is not None else svc.view()
    except DomainRefused as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(400, "This app has no definition yet.") from exc
    finally:
        await client.close()
        await _tell(project_id, said)


@router.get("/api/projects/{project_id}/domains")
async def list_domains(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """The app's addresses, their records and status. Reading never calls
    Vercel; Check now does."""
    from services.deploy.domains import DomainService, project_root, vercel_project_name
    project = await _project(project_id, user, db)
    svc = DomainService(output_dir=str(project_root(project.output_dir)), client=None,
                        project_name=vercel_project_name(project.short_id))
    return svc.view()


@router.post("/api/projects/{project_id}/domains")
async def add_domain(project_id: uuid.UUID, body: AddDomain, user: PlatformUser = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    async def act(svc):
        await svc.connect(body.name)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.post("/api/projects/{project_id}/domains/{name}/check")
async def check_domain(project_id: uuid.UUID, name: str, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    async def act(svc):
        await svc.refresh(name)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.post("/api/projects/{project_id}/domains/{name}/main")
async def make_main(project_id: uuid.UUID, name: str, user: PlatformUser = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    async def act(svc):
        await svc.make_main(name)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.delete("/api/projects/{project_id}/domains/{name}")
async def remove_domain(project_id: uuid.UUID, name: str, user: PlatformUser = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    async def act(svc):
        await svc.remove(name)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.put("/api/projects/{project_id}/domains/old-address")
async def set_old_address(project_id: uuid.UUID, body: OldAddress, user: PlatformUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    async def act(svc):
        await svc.set_old_address(body.mode)
        return svc.view()
    return await _run(project_id, user, db, act)


@router.put("/api/projects/{project_id}/domains/tentoro")
async def rename_tentoro(project_id: uuid.UUID, body: AddDomain, user: PlatformUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Give the app's Tentoro address another name (`aqua`)."""
    async def act(svc):
        await svc.rename_tentoro(body.name)
        return svc.view()
    return await _run(project_id, user, db, act)
