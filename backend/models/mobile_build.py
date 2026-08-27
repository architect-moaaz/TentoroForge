"""MOBILE-C — build state row per EAS Build invocation.

Every click of "Build mobile app" in the Publish dialog inserts a row
here and walks it through pending → in_progress → completed/failed
(mirroring EAS Build's own status field). The eas_build_id is stored
so subsequent polls and re-checks reuse the same EAS build (rather
than starting a new one).

Slice C — this model + the endpoint that creates rows and drives them
via `services.eas_client`.
Slice D — the Publish-dialog "Mobile app" tab that reads a per-project
list of these rows via GET /api/projects/{id}/mobile-builds.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MobileBuild(Base):
    __tablename__ = "mobile_builds"
    __table_args__ = (
        # "latest builds for this project" — powers the Publish-dialog
        # history list + the "already-running preview build?" idempotency
        # check on POST.
        Index("mobile_builds_project_created_idx", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Which user hit the button — for the audit trail. Nullable because
    # a future scheduled/system-triggered build wouldn't have a user.
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # "preview" (internal-distribution APK / device IPA / sim IPA) or
    # "production" (store-submittable AAB / IPA). Matches the eas.json
    # build profile the scaffolder emits.
    profile: Mapped[str] = mapped_column(String(32), nullable=False)
    # "android" or "ios".
    platform: Mapped[str] = mapped_column(String(16), nullable=False)

    # pending → in_progress → completed / failed / canceled.
    # Kept as a bare string (not enum) so a future EAS status value we
    # haven't seen yet won't require a schema migration to land.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )

    # --- EAS-specific ---
    # UUID assigned by EAS Build. Populated after the CLI returns.
    # NULL means the CLI invocation itself failed (no build was queued).
    eas_build_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Public URL where the APK/AAB/IPA can be downloaded. Populated on
    # completion; NULL on failure or in-progress.
    artifact_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Link to the EAS Build page for humans to inspect logs.
    logs_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Human-readable summary of the failure — from either the CLI stderr
    # or the EAS status.errorMessage. Kept as free text so we can put
    # anything useful in it without forcing a taxonomy.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
