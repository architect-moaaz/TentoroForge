"""merge divergent heads

Revision ID: f3ffbf62087c
Revises: c3d4e5f6a7b8, d1e2f3a4b5c6
Create Date: 2026-05-02 17:56:58.309136
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3ffbf62087c'
down_revision: Union[str, None] = ('c3d4e5f6a7b8', 'd1e2f3a4b5c6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
