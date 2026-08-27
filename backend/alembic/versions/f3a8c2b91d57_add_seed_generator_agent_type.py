"""add seed_generator agent type

Revision ID: f3a8c2b91d57
Revises: 1dbaa6f922f4
Create Date: 2026-02-28 23:30:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f3a8c2b91d57'
down_revision: Union[str, None] = '1dbaa6f922f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE agent_type ADD VALUE IF NOT EXISTS 'seed_generator'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values easily.
    pass
