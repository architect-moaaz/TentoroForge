"""add conversations.seq — monotonic ordering key

The chat restore endpoint ordered conversation rows by `created_at`, which is
`func.now()` = the TRANSACTION start time in Postgres, so every row written in
the same transaction shares an identical timestamp. With random uuid4 primary
keys there was no tiebreak, so rows came back in arbitrary heap order → the
conversation visibly reordered on every project reload. This adds a monotonic
BIGINT identity `seq` and backfills existing rows in created_at order, giving a
stable, insertion-ordered sort key.

Revision ID: cf3a91b2d7e4
Revises: ba25497d895b
Create Date: 2026-08-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "cf3a91b2d7e4"
down_revision = "ba25497d895b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the column nullable so we can backfill deterministically.
    op.add_column("conversations", sa.Column("seq", sa.BigInteger(), nullable=True))
    # 2. Backfill existing rows in creation order (created_at, then id for a
    #    stable tiebreak within a shared timestamp).
    op.execute(
        """
        UPDATE conversations c
        SET seq = sub.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS rn
            FROM conversations
        ) sub
        WHERE c.id = sub.id
        """
    )
    # 3. Create a sequence continuing past the backfilled max, and wire it as
    #    the column default so new inserts auto-populate.
    op.execute("CREATE SEQUENCE IF NOT EXISTS conversations_seq_seq OWNED BY conversations.seq")
    op.execute(
        "SELECT setval('conversations_seq_seq', COALESCE((SELECT MAX(seq) FROM conversations), 0) + 1, false)"
    )
    op.execute("ALTER TABLE conversations ALTER COLUMN seq SET DEFAULT nextval('conversations_seq_seq')")
    op.alter_column("conversations", "seq", nullable=False)
    # 4. Index for the per-project ordered read.
    op.create_index("ix_conv_project_seq", "conversations", ["project_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_conv_project_seq", table_name="conversations")
    op.execute("ALTER TABLE conversations ALTER COLUMN seq DROP DEFAULT")
    op.drop_column("conversations", "seq")
    op.execute("DROP SEQUENCE IF EXISTS conversations_seq_seq")
