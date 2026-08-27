"""Webhook endpoints — CRUD webhook subscriptions."""

import uuid
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.webhook import Webhook
from services.project_service import get_project_with_auth
from services.webhook_service import EVENTS

router = APIRouter(tags=["webhooks"])


class WebhookCreate(BaseModel):
    url: str
    events: list[str] = ["*"]
    description: str | None = None
    secret: str | None = None


class WebhookUpdate(BaseModel):
    url: str | None = None
    events: list[str] | None = None
    description: str | None = None
    is_active: bool | None = None


class WebhookResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    events: list[str] | None
    is_active: bool
    description: str | None
    last_triggered_at: str | None
    failure_count: int
    created_at: str

    model_config = {"from_attributes": True}


@router.get(
    "/api/projects/{project_id}/webhooks",
    response_model=list[WebhookResponse],
)
async def list_webhooks(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(Webhook)
        .where(Webhook.project_id == project_id)
        .order_by(Webhook.created_at.desc())
    )
    return result.scalars().all()


@router.post(
    "/api/projects/{project_id}/webhooks",
    response_model=WebhookResponse,
    status_code=201,
)
async def create_webhook(
    project_id: uuid.UUID,
    req: WebhookCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)

    webhook = Webhook(
        project_id=project_id,
        url=req.url,
        events=req.events,
        description=req.description,
        secret=req.secret or secrets.token_hex(32),
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    return webhook


@router.put(
    "/api/projects/{project_id}/webhooks/{webhook_id}",
    response_model=WebhookResponse,
)
async def update_webhook(
    project_id: uuid.UUID,
    webhook_id: uuid.UUID,
    req: WebhookUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.project_id == project_id,
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(webhook, field, value)

    await db.commit()
    await db.refresh(webhook)
    return webhook


@router.delete(
    "/api/projects/{project_id}/webhooks/{webhook_id}",
    status_code=204,
)
async def delete_webhook(
    project_id: uuid.UUID,
    webhook_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.project_id == project_id,
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    await db.delete(webhook)
    await db.commit()


@router.get("/api/webhook-events")
async def list_available_events(
    user: PlatformUser = Depends(get_current_user),
):
    """List all available webhook events."""
    return {"events": EVENTS}
