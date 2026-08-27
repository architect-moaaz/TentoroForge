"""add workflow assignment policies table

Revision ID: b8c4d2e5f7a1
Revises: a7b3c1d2e4f6
Create Date: 2026-03-01 01:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c4d2e5f7a1"
down_revision: Union[str, None] = "a7b3c1d2e4f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_assignment_policies",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.String(255), nullable=False),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("assign_type", sa.String(50), nullable=False),
        sa.Column("assign_target", sa.UUID(), nullable=True),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column("escalate_to", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_wf_assignment_project", "workflow_assignment_policies", ["project_id"])
    op.create_index("idx_wf_assignment_workflow", "workflow_assignment_policies", ["project_id", "workflow_id"])


def downgrade() -> None:
    op.drop_table("workflow_assignment_policies")
