"""add project.brief JSONB column

Revision ID: db07082026
Revises: aa07082026
Create Date: 2026-08-07

Adds a nullable JSONB `brief` column on `projects` to persist the
LLM-authored :class:`schemas.design_brief.DesignBrief` per project.

Phase 1 of the design-brief rollout — additive only. Null for every
existing project; populated when FORGE_BRIEF_AUTHOR is on and Discovery
completes for a new generation.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "db07082026"
down_revision = "aa07082026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("brief", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "brief")
