"""add new agent type enum values

Revision ID: e24244544c86
Revises: a51e0d4dfcf4
Create Date: 2026-02-28 23:13:33.846179
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e24244544c86'
down_revision: Union[str, None] = 'a51e0d4dfcf4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_VALUES = ['planner', 'refiner', 'explainer', 'scaffolder', 'code_editor']


def upgrade() -> None:
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE agent_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values easily.
    # A full enum recreation would be needed; skipping for safety.
    pass
