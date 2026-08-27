"""Discovery session model — tracks multi-turn requirement discovery conversations."""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    Index,
    Enum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class DiscoveryStatus(str, PyEnum):
    active = "active"
    brief_ready = "brief_ready"
    converted = "converted"
    abandoned = "abandoned"


class DiscoverySession(Base):
    __tablename__ = "discovery_sessions"
    __table_args__ = (
        Index("ix_discovery_org", "org_id"),
        Index("ix_discovery_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[DiscoveryStatus] = mapped_column(
        Enum(DiscoveryStatus, name="discovery_status"),
        default=DiscoveryStatus.active,
    )
    discovery_type: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(255))
    messages: Mapped[list | None] = mapped_column(JSONB, default=list)
    brief: Mapped[dict | None] = mapped_column(JSONB)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
