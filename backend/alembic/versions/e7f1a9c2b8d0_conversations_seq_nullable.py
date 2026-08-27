"""conversations.seq — drop NOT NULL (crash-proof), keep sequence default

The NOT-NULL on conversations.seq (added in cf3a91b2d7e4) caused EVERY chat /
Smith / generation message write to 500: the ORM model declared seq without a
server_default, so SQLAlchemy sent an explicit `seq=NULL` and Postgres rejected
it. The real fix is the model server_default (so seq is omitted from the INSERT
and the sequence fills it). Dropping NOT NULL here is belt-and-suspenders: even a
stray raw-SQL NULL can no longer crash a message write; the restore query orders
`seq ASC NULLS LAST, created_at`, so a null simply sorts last.

Revision ID: e7f1a9c2b8d0
Revises: 55983c37a554
Create Date: 2026-08-06
"""
from __future__ import annotations

from alembic import op


revision = "e7f1a9c2b8d0"
down_revision = "55983c37a554"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the DEFAULT nextval(...) — only relax the NOT NULL constraint.
    op.execute("ALTER TABLE conversations ALTER COLUMN seq DROP NOT NULL")


def downgrade() -> None:
    # Backfill any nulls before re-imposing NOT NULL.
    op.execute(
        "UPDATE conversations SET seq = nextval('conversations_seq_seq') WHERE seq IS NULL"
    )
    op.execute("ALTER TABLE conversations ALTER COLUMN seq SET NOT NULL")
