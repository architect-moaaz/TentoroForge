"""Durable Smith preferences — one row per (org, user, key) (Phase 1c).

Powers the "I said don't ask me to confirm anymore" pattern (UAT tests
81, 82, 86, 132–135). A user's preference set is injected into Smith's
system prompt on every turn so the assistant applies the standing
rules ("confirm on delete", "prefer purple", etc.) without the user
restating them each session.

Scoping decision:
* (org, user, key) is unique. Later phases can add a project_id
  optional column for per-project overrides — schema-forward
  compatible via a nullable column.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class SmithPreference(Base):
    __tablename__ = "smith_preferences"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "user_id", "key",
            name="uq_smith_prefs_org_user_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # No FK — user records live in NextAuth's own tables and we
        # only need the id as a stable string. Matches the pattern
        # used elsewhere for user_id refs.
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(length=80), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
