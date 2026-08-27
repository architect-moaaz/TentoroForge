"""Notification endpoints — list, mark-read, count unread."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services.notification_service import NotificationService
from schemas.notification import NotificationResponse

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    return await service.list_for_user(
        user_id=user.id,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )


@router.get("/count")
async def count_unread(
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    count = await service.count_unread(user.id)
    return {"unread_count": count}


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    marked = await service.mark_read(notification_id, user.id)
    if not marked:
        raise HTTPException(status_code=404, detail="Notification not found")
    await db.commit()


@router.post("/read-all", status_code=204)
async def mark_all_read(
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    await service.mark_all_read(user.id)
    await db.commit()
