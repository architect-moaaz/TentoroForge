"""Which of the platform's features an organisation may use — the cockpit's
switchboard.

Every feature is on unless it takes an app's source code out of the
platform (the Code tab, code export, publishing, mobile builds), which are
off until the super admin turns them on. A row here is an explicit
setting: one per feature for the platform as a whole (the default every
organisation inherits) and one per feature per organisation (an override).
No row means "as the catalogue says". Each row carries the reason and the
hand that set it; the audit trail carries every change.

No Postgres enums, no JSONB, Python-side ids, as the credit tables: what
the in-memory test database can hold as they are.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class FeatureSetting(Base):
    __tablename__ = "feature_settings"
    __table_args__ = (UniqueConstraint("scope_kind", "scope_id", "feature_key", name="uq_feature_setting_scope"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    #: platform | org
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: "" for the platform; an organisation id.
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    set_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
