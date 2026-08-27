"""merge decision-tables + smith/platform/deploy heads

Revision ID: ba25497d895b
Revises: b8d4e1f9a3c2, mb2907c3d4e5
Create Date: 2026-08-03 11:45:23.426146
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ba25497d895b'
down_revision: Union[str, None] = ('b8d4e1f9a3c2', 'mb2907c3d4e5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
