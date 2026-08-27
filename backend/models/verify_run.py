"""SV-4 — one row per Self-Verify Pass run.

Records what was run + the FaultReport JSON so the UI can render past
runs and regression detection can dedup faults across runs.

Lifecycle:  pending → running → done | failed
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class VerifyRun(Base):
    __tablename__ = "verify_runs"
    __table_args__ = (
        Index("verify_runs_project_created_idx", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    invoked_by: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="auto_post_gen",
    )  # auto_post_gen | user_ui | user_chat | smith_edit
    target: Mapped[str] = mapped_column(String(16), nullable=False)  # preview | deploy
    scope: Mapped[str] = mapped_column(String(255), nullable=False, server_default="*")
    runner_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending",
    )  # pending | running | done | failed | superseded

    interactions_run: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interactions_passed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    faults_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rounds_run: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Full RunReport JSON + optional RemediationReport after Smith rounds
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    remediation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
