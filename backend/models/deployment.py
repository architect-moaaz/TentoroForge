"""Publish-flow state — one row per Deploy invocation.

Every click of the Publish button in the editor inserts a row here and
walks it through pending → building → deploying → succeeded/failed.
The Vercel + Neon ids are stored so redeploys reuse the same Vercel
project and Neon database (rather than orphaning the previous ones)
and so the rollback endpoint can re-promote an earlier deployment.

Spec: docs/superpowers/plans/2026-07-23-generated-app-deploy-vercel.md.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        # Fast lookup for "latest deployment for this project" — powers
        # the redeploy path (which reuses vercel_project_id / neon_project_id)
        # and the DeploymentHistory list in the editor.
        Index("deployments_project_created_idx", "project_id", "created_at"),
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
    # "vercel" today; "aws" when the AWS provider lands. The DeployProvider
    # interface reads this to pick which provider handles a rollback.
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    # pending → snapshot → provision_db → migrate → upload → build → activate
    # → succeeded (or failed). Matches the DeployEvent.stage enum in
    # services.deploy.provider (with succeeded/failed as terminal states).
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Vercel-specific ---
    vercel_project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vercel_deployment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Neon-specific ---
    neon_project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    neon_branch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- audit ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # --- source-of-truth for what was shipped ---
    # Captured at publish start from the generated app's own git repo
    # (each app dir is a git repo in its own right) so history rows can
    # show "commit abc1234" even after the working tree moves on.
    git_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    git_commit_subject: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    # From the app's package.json `version` field. Optional — apps
    # without a semver bumped on each change will just show sha.
    app_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
