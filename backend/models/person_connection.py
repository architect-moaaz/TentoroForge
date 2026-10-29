"""A person's own connection to an outside service — one row per (person, provider).

`platform_integrations` holds the ORGANISATION's keys: one Figma token every
member builds with. That token opens only the files its owner can open, so a
client's design shared with one tester read as "not found" (2026-10-29) and
had to be copied into a file the shared token could see. A person who signs in
to Figma with OAuth gets their own row here, and Forge reads their files with
it while they are the one acting.

Values are sealed the way the organisation's are
(`services.platform_integrations_crypto`, under a subkey of their own), and
this row is never returned by any API: the account's name is, the token is not.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class PersonConnection(Base):
    __tablename__ = "platform_person_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_person_connections_user_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The account on the other side, for display: never a secret.
    account_id: Mapped[str | None] = mapped_column(String(128))
    account_name: Mapped[str | None] = mapped_column(String(255))
    account_email: Mapped[str | None] = mapped_column(String(255))
    scope: Mapped[str | None] = mapped_column(String(255))
    access_ct: Mapped[str] = mapped_column(Text, nullable=False)
    access_iv: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_ct: Mapped[str | None] = mapped_column(Text)
    refresh_iv: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
