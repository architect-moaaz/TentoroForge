"""payment gateways an organisation takes money through, and each app's webhook at them

Set up once in Settings → Payments (test and live keys, encrypted), chosen per
application. The webhook table keeps what Forge registered at a gateway for
each application and side, so a publish registers once and reuses it.

Revision ID: pg1030_payment_gateways
Revises: mg1103_gallery_run_jobs
Create Date: 2026-10-30
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "pg1030_payment_gateways"
down_revision = "mg1103_gallery_run_jobs"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "payment_gateways",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("coverage", sa.String(16), nullable=False, server_default="both"),
        sa.Column("home_country", sa.String(2)),
        sa.Column("currencies", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("test_ct", sa.Text),
        sa.Column("test_iv", sa.Text),
        sa.Column("live_ct", sa.Text),
        sa.Column("live_iv", sa.Text),
        sa.Column("checks", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", UUID, sa.ForeignKey("platform_users.id", ondelete="SET NULL")),
        sa.Column("updated_by", UUID, sa.ForeignKey("platform_users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_payment_gateways_org_id", "payment_gateways", ["org_id"])
    op.create_table(
        "payment_gateway_webhooks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("gateway_id", UUID, sa.ForeignKey("payment_gateways.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("provider_ref", sa.String(128)),
        sa.Column("secret_ct", sa.Text),
        sa.Column("secret_iv", sa.Text),
        sa.Column("status", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("detail", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("gateway_id", "project_id", "side", name="uq_payment_gateway_webhooks_gateway_project_side"),
    )
    op.create_index("ix_payment_gateway_webhooks_gateway_id", "payment_gateway_webhooks", ["gateway_id"])
    op.create_index("ix_payment_gateway_webhooks_project_id", "payment_gateway_webhooks", ["project_id"])


def downgrade() -> None:
    op.drop_table("payment_gateway_webhooks")
    op.drop_table("payment_gateways")
