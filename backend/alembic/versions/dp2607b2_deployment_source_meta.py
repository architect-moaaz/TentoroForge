"""add deployments.git_sha, git_commit_subject, app_version

Captures which build was shipped so the History view can show the
commit + version alongside status/who/how-long.

Revision ID: dp2607b2c4d5
Revises: dp2607a1b2c3
Create Date: 2026-07-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "dp2607b2c4d5"
down_revision = "dp2607a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deployments",
        sa.Column("git_sha", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "deployments",
        sa.Column("git_commit_subject", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "deployments",
        sa.Column("app_version", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deployments", "app_version")
    op.drop_column("deployments", "git_commit_subject")
    op.drop_column("deployments", "git_sha")
