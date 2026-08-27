"""add fault_records table

Revision ID: svst5_faults
Revises: sv3108a1b2c3, cf3a91b2d7e4, db07082026
Create Date: 2026-08-15

SV-STRICT-5. One row per fault observed across the lifetime of a
project — the substrate for compounding-learning analytics on top of
self-verify. Merges the divergent heads so ``alembic upgrade head``
doesn't complain about multiple.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "svst5_faults"
down_revision = ("sv3108a1b2c3", "cf3a91b2d7e4", "db07082026")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fault_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("verify_runs.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("layer", sa.String(length=16), nullable=False),
        sa.Column("w_slot", sa.String(length=8), nullable=False),
        sa.Column("component_id", sa.String(length=255), nullable=True),
        sa.Column("contract_id", sa.String(length=255), nullable=True),
        sa.Column("component_type", sa.String(length=16), nullable=True),
        sa.Column("route", sa.String(length=255), nullable=True),
        sa.Column("generation_hash", sa.String(length=64), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("narrative", sa.String(length=1024), nullable=True),
        sa.Column("fix_applied", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("fix_stuck", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("fault_records_project_created_idx", "fault_records",
                    ["project_id", "created_at"])
    op.create_index("fault_records_project_signature_idx", "fault_records",
                    ["project_id", "signature"])
    op.create_index("fault_records_signature_idx", "fault_records",
                    ["signature"])


def downgrade() -> None:
    op.drop_index("fault_records_signature_idx", table_name="fault_records")
    op.drop_index("fault_records_project_signature_idx", table_name="fault_records")
    op.drop_index("fault_records_project_created_idx", table_name="fault_records")
    op.drop_table("fault_records")
