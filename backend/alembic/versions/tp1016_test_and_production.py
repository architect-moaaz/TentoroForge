"""an app is published to Test or to Production

Each deployment says which side of the app it went to, with a fingerprint of
the files it shipped and, for a promotion, the test deployment it took them
from. Each project keeps where Publish sends it. Everything that existed went
to production, and keeps publishing there; new projects start on test (the
model's default).

Revision ID: tp1016_test_and_production
Revises: ms1016_mobile_build_submit
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "tp1016_test_and_production"
down_revision = "ms1016_mobile_build_submit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deployments", sa.Column("environment", sa.String(16), nullable=False,
                                           server_default="production"))
    op.add_column("deployments", sa.Column("source_digest", sa.String(64), nullable=True))
    op.add_column("deployments", sa.Column("promoted_from", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("deployments_promoted_from_fkey", "deployments", "deployments",
                          ["promoted_from"], ["id"], ondelete="SET NULL")
    op.create_index("deployments_project_env_created_idx", "deployments",
                    ["project_id", "environment", "created_at"])
    op.add_column("projects", sa.Column("publish_target", sa.String(16), nullable=False,
                                        server_default="production"))


def downgrade() -> None:
    op.drop_column("projects", "publish_target")
    op.drop_index("deployments_project_env_created_idx", table_name="deployments")
    op.drop_constraint("deployments_promoted_from_fkey", "deployments", type_="foreignkey")
    op.drop_column("deployments", "promoted_from")
    op.drop_column("deployments", "source_digest")
    op.drop_column("deployments", "environment")
