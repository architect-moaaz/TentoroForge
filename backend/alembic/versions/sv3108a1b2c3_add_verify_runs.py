"""add verify_runs table

Revision ID: sv3108a1b2c3
Revises: mb2907c3d4e5
Create Date: 2026-08-01

SV-4. One row per Self-Verify Pass run. Records what was tested, the
raw FaultReport from the runner, and (after Smith rounds) the
RemediationReport that closed out the loop.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "sv3108a1b2c3"
# Merge migration: consumes both pre-existing heads (mobile_builds +
# enterprise_readiness_tables) so `alembic upgrade head` doesn't
# complain about multiple heads. Adds the verify_runs table too.
down_revision = ("mb2907c3d4e5", "d1e2f3a4b5c6", "b8d4e1f9a3c2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "verify_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("triggered_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("platform_users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("invoked_by", sa.String(length=32), nullable=False,
                  server_default="auto_post_gen"),
        sa.Column("target", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=False,
                  server_default="*"),
        sa.Column("runner_run_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False,
                  server_default="pending"),
        sa.Column("interactions_run", sa.Integer(), nullable=True),
        sa.Column("interactions_passed", sa.Integer(), nullable=True),
        sa.Column("faults_count", sa.Integer(), nullable=True),
        sa.Column("rounds_run", sa.Integer(), nullable=True),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("remediation", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("verify_runs_project_created_idx", "verify_runs",
                    ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("verify_runs_project_created_idx", table_name="verify_runs")
    op.drop_table("verify_runs")
