"""a build or a Smith turn is on record while it runs (run_jobs)

Revision ID: rj1101_run_jobs
Revises: fc1029_person_connections
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "rj1101_run_jobs"
down_revision = "fc1029_person_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=True),
        sa.Column("actor", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("resume", postgresql.JSONB(), nullable=True),
        sa.Column("worker", sa.String(128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_run_jobs_status", "run_jobs", ["status"])
    op.create_index("ix_run_jobs_project_created", "run_jobs", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_run_jobs_project_created", table_name="run_jobs")
    op.drop_index("ix_run_jobs_status", table_name="run_jobs")
    op.drop_table("run_jobs")
