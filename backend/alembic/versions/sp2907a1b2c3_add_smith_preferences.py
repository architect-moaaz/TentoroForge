"""add smith_preferences table

Revision ID: sp2907a1b2c3
Revises: dp2607b2c4d5
Create Date: 2026-07-29

Phase 1c of the Smith coverage-lift roadmap. Persists a user's standing
preferences ("always confirm on delete", "prefer purple", etc.) across
sessions so Smith reads them at turn ingress and applies them without
the user restating them each time.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "sp2907a1b2c3"
down_revision = "dp2607b2c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "smith_preferences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
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
        sa.UniqueConstraint(
            "org_id", "user_id", "key",
            name="uq_smith_prefs_org_user_key",
        ),
    )
    op.create_index(
        "ix_smith_prefs_org_user",
        "smith_preferences",
        ["org_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_smith_prefs_org_user", table_name="smith_preferences")
    op.drop_table("smith_preferences")
