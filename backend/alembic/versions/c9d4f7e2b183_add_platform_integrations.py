"""add platform_integrations

Revision ID: c9d4f7e2b183
Revises: a9b7c2e8f4d1
Create Date: 2026-07-22 12:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d4f7e2b183'
down_revision: Union[str, None] = 'a9b7c2e8f4d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'platform_integrations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('value_ct', sa.Text(), nullable=True),
        sa.Column('value_iv', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by'], ['platform_users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'provider', 'key', name='uq_platform_integrations_org_provider_key'),
    )
    op.create_index('ix_platform_integrations_org_id', 'platform_integrations', ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_platform_integrations_org_id', table_name='platform_integrations')
    op.drop_table('platform_integrations')
