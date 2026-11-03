"""a person's own connection to an outside service (Connect Figma)

Revision ID: fc1029_person_connections
Revises: tp1016_test_and_production
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "fc1029_person_connections"
down_revision = "tp1016_test_and_production"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_person_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=True),
        sa.Column("account_name", sa.String(255), nullable=True),
        sa.Column("account_email", sa.String(255), nullable=True),
        sa.Column("scope", sa.String(255), nullable=True),
        sa.Column("access_ct", sa.Text(), nullable=False),
        sa.Column("access_iv", sa.Text(), nullable=False),
        sa.Column("refresh_ct", sa.Text(), nullable=True),
        sa.Column("refresh_iv", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_person_connections_user_provider"),
    )
    op.create_index("ix_platform_person_connections_user_id", "platform_person_connections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_platform_person_connections_user_id", table_name="platform_person_connections")
    op.drop_table("platform_person_connections")
