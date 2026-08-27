"""add platform_mcp_servers

Registry of approved MCP servers per organisation. Rows own the server
URL, transport, and (encrypted) auth credentials; the Agent Builder's
`tool_type: mcp` nodes reference a row by id.

Revision ID: mcp010101a2b3
Revises: sv3108a1b2c3
Create Date: 2026-08-01 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'mcp010101a2b3'
down_revision: Union[str, None] = 'sv3108a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'platform_mcp_servers',
        sa.Column(
            'id',
            sa.UUID(),
            server_default=sa.text('gen_random_uuid()'),
            nullable=False,
        ),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('server_url', sa.String(length=1024), nullable=False),
        sa.Column(
            'transport',
            sa.String(length=16),
            server_default=sa.text("'http'"),
            nullable=False,
        ),
        sa.Column(
            'auth_kind',
            sa.String(length=32),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
        sa.Column('auth_secret_ct', sa.Text(), nullable=True),
        sa.Column('auth_secret_iv', sa.Text(), nullable=True),
        sa.Column('auth_header_name', sa.String(length=64), nullable=True),
        sa.Column(
            'enabled',
            sa.Boolean(),
            server_default=sa.text('true'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by'], ['platform_users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_platform_mcp_servers_org_name'),
        sa.CheckConstraint(
            "transport IN ('http', 'sse')",
            name='ck_platform_mcp_servers_transport',
        ),
        sa.CheckConstraint(
            "auth_kind IN ('none', 'bearer', 'apikey_header')",
            name='ck_platform_mcp_servers_auth_kind',
        ),
    )
    op.create_index(
        'ix_platform_mcp_servers_org_id',
        'platform_mcp_servers',
        ['org_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_platform_mcp_servers_org_id', table_name='platform_mcp_servers')
    op.drop_table('platform_mcp_servers')
