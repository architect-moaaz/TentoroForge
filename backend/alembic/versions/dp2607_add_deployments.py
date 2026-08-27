"""add deployments table

Revision ID: dp2607a1b2c3
Revises: c9d4f7e2b183
Create Date: 2026-07-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "dp2607a1b2c3"
down_revision = "c9d4f7e2b183"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("vercel_project_id", sa.String(length=64), nullable=True),
        sa.Column("vercel_deployment_id", sa.String(length=64), nullable=True),
        sa.Column("neon_project_id", sa.String(length=64), nullable=True),
        sa.Column("neon_branch_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_deployments_project_id", "deployments", ["project_id"])
    op.create_index(
        "deployments_project_created_idx",
        "deployments",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("deployments_project_created_idx", table_name="deployments")
    op.drop_index("ix_deployments_project_id", table_name="deployments")
    op.drop_table("deployments")
