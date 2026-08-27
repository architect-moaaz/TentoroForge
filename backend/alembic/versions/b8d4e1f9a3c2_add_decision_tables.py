"""add decision tables (decision_tables, versions, execution logs)

The decision-table models (models/decision.py) were live via routers/decisions.py
and used by the business-rules `decision_table` type, but had NO migration — so the
tables existed only in tests (Base.metadata.create_all) and the endpoints 500'd in
prod. This creates them for real. Mirrors models/decision.py exactly.

Revision ID: b8d4e1f9a3c2
Revises: a9b7c2e8f4d1
Create Date: 2026-07-28 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8d4e1f9a3c2"
down_revision: Union[str, None] = "a9b7c2e8f4d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_tables",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_decision_table_project", "decision_tables", ["project_id"])

    op.create_table(
        "decision_table_versions",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("decision_table_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["decision_table_id"], ["decision_tables.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_decision_version_table", "decision_table_versions", ["decision_table_id"])
    op.create_index(
        "idx_decision_version_number", "decision_table_versions", ["decision_table_id", "version"]
    )

    op.create_table(
        "decision_execution_logs",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("decision_table_id", sa.UUID(), nullable=False),
        sa.Column("workflow_instance_id", sa.UUID(), nullable=True),
        sa.Column("inputs", postgresql.JSONB(), nullable=True),
        sa.Column("outputs", postgresql.JSONB(), nullable=True),
        sa.Column("matched_rule_ids", postgresql.JSONB(), nullable=True),
        sa.Column("hit_policy", sa.String(1), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["decision_table_id"], ["decision_tables.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_decision_log_table", "decision_execution_logs", ["decision_table_id"])
    op.create_index(
        "idx_decision_log_workflow", "decision_execution_logs", ["workflow_instance_id"]
    )


def downgrade() -> None:
    op.drop_table("decision_execution_logs")
    op.drop_table("decision_table_versions")
    op.drop_table("decision_tables")
