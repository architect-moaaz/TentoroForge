"""change assign_target from UUID to VARCHAR(500)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-03 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "workflow_assignment_policies",
        "assign_target",
        type_=sa.String(500),
        existing_type=sa.UUID(),
        existing_nullable=True,
        postgresql_using="assign_target::text",
    )


def downgrade() -> None:
    op.alter_column(
        "workflow_assignment_policies",
        "assign_target",
        type_=sa.UUID(),
        existing_type=sa.String(500),
        existing_nullable=True,
        postgresql_using="assign_target::uuid",
    )
