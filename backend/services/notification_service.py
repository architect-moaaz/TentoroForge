"""In-app notification service — database-backed notifications with CRUD."""

import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification

logger = logging.getLogger(__name__)


class NotificationService:
    """Manages in-app notifications."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: uuid.UUID,
        notification_type: str,
        title: str,
        content: str,
        link: str | None = None,
        metadata: dict | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            type=notification_type,
            title=title,
            content=content,
            link=link,
            metadata_=metadata or {},
        )
        self.db.add(notification)
        await self.db.flush()
        logger.info("Created notification %s for user %s", notification.id, user_id)
        return notification

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Notification]:
        q = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if unread_only:
            q = q.where(Notification.read_at.is_(None))
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def count_unread(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
        )
        return result.scalar() or 0

    async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
            .values(read_at=datetime.now(timezone.utc))
        )
        await self.db.flush()
        return result.rowcount > 0

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=datetime.now(timezone.utc))
        )
        await self.db.flush()
        return result.rowcount
