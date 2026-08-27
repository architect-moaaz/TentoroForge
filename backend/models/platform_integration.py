"""Platform-side credential store — one row per (org, provider, key).

Values are encrypted at rest (see services.platform_integrations_crypto).
The generation pipeline reads this table to populate a newly-generated
app's .env.local; the manual sync endpoint re-reads and rewrites .env.local
for an existing project.

Spec: docs/superpowers/specs/2026-07-22-integrations-settings.md.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class PlatformIntegration(Base):
    __tablename__ = "platform_integrations"
    __table_args__ = (
        UniqueConstraint("org_id", "provider", "key", name="uq_platform_integrations_org_provider_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Ciphertext + IV base64. Nullable so a "cleared" row is distinguishable
    # from "never set" (row present but ct=null == cleared; row absent == unset).
    value_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_iv: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True,
    )
