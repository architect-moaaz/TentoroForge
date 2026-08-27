"""add mobile_builds table

Revision ID: mb2907c3d4e5
Revises: sp2907a1b2c3
Create Date: 2026-07-30

MOBILE-C. One row per EAS Build invocation triggered from the Publish
dialog. Walks pending → in_progress → completed / failed / canceled;
stores the EAS build id + artifact URL for the download UI.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "mb2907c3d4e5"
down_revision = "sp2907a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mobile_builds",
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
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("profile", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("eas_build_id", sa.String(length=64), nullable=True),
        sa.Column("artifact_url", sa.Text(), nullable=True),
        sa.Column("logs_url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "mobile_builds_project_id_idx",
        "mobile_builds",
        ["project_id"],
    )
    op.create_index(
        "mobile_builds_project_created_idx",
        "mobile_builds",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("mobile_builds_project_created_idx", table_name="mobile_builds")
    op.drop_index("mobile_builds_project_id_idx", table_name="mobile_builds")
    op.drop_table("mobile_builds")
