"""merge conversation-seq + mcp-servers heads

Revision ID: 02b5f1d84c52
Revises: cf3a91b2d7e4, mcp010101a2b3
Create Date: 2026-08-05 10:36:32.392526
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02b5f1d84c52'
down_revision: Union[str, None] = ('cf3a91b2d7e4', 'mcp010101a2b3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
