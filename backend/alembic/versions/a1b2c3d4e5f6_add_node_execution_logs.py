"""add node_execution_logs table

Revision ID: a1b2c3d4e5f6
Revises: f3a8c2b91d57
Create Date: 2026-03-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f3a8c2b91d57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use raw SQL throughout: SQLAlchemy's create_type=False didn't reliably
    # suppress duplicate CREATE TYPE emission in this version stack, and the
    # other migration head independently expects this enum to exist when
    # the heads merge. Raw SQL with idempotent guards bypasses both issues.
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE node_execution_status AS ENUM ('started', 'completed', 'failed', 'skipped');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        CREATE TABLE node_execution_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_instance_id UUID NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
            node_id VARCHAR(255) NOT NULL,
            node_type VARCHAR(100) NOT NULL,
            node_label VARCHAR(255),
            status node_execution_status NOT NULL,
            input_snapshot JSONB,
            output_snapshot JSONB,
            error_message TEXT,
            started_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            duration_ms INTEGER
        )
    """)
    op.execute("CREATE INDEX ix_nel_instance ON node_execution_logs (workflow_instance_id)")
    op.execute("CREATE INDEX ix_nel_node_id ON node_execution_logs (node_id)")
    op.execute("CREATE INDEX ix_nel_status ON node_execution_logs (status)")


def downgrade() -> None:
    op.drop_index("ix_nel_status", table_name="node_execution_logs")
    op.drop_index("ix_nel_node_id", table_name="node_execution_logs")
    op.drop_index("ix_nel_instance", table_name="node_execution_logs")
    op.drop_table("node_execution_logs")
    sa.Enum(name="node_execution_status").drop(op.get_bind(), checkfirst=True)
