"""credit per organisation and spending limits — the policy the cockpit keeps

A signed credit entry per organisation (opening, top-up, adjustment, refund)
with its reason and who made it; one limit row per scope and period.

Revision ID: cr1015_credits
Revises: sa1015_super_admin
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "cr1015_credits"
down_revision = "sa1015_super_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("by_user_id", UUID(as_uuid=True), sa.ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_credit_entries_org_at", "credit_entries", ["org_id", "at"])

    op.create_table(
        "spend_limits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("period", sa.String(8), nullable=False),
        sa.Column("amount_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("set_by", UUID(as_uuid=True), sa.ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scope_kind", "scope_id", "period", name="uq_spend_limit_scope_period"),
    )


def downgrade() -> None:
    op.drop_table("spend_limits")
    op.drop_index("ix_credit_entries_org_at", table_name="credit_entries")
    op.drop_table("credit_entries")
