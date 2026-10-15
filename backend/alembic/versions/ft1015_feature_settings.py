"""feature settings — which of the platform's features an organisation may use

One row per explicit setting: a platform default or an organisation's
override, with the reason and who set it. No row means the catalogue's
default (on, unless the feature takes source code out of the platform).

Revision ID: ft1015_features
Revises: cr1015_credits
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "ft1015_features"
down_revision = "cr1015_credits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("feature_key", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("set_by", UUID(as_uuid=True), sa.ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scope_kind", "scope_id", "feature_key", name="uq_feature_setting_scope"),
    )


def downgrade() -> None:
    op.drop_table("feature_settings")
