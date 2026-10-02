"""drop runtime_exceptions.request_body and user_context

Two JSONB columns held the whole POST body and the whole session user of
whatever crashed in a generated application: a customer's record and a
customer's identity, copied into the platform's own tables. That data belongs
to the owner of the application, not to us.

The reporter no longer sends them, `RuntimeExceptionIn` rejects them, and the
account Smith reads is the project's own `.forge/incidents.jsonl`, which
carries the KEYS a control sent and never the values. These columns are the
last place the old shape could come to rest, so they go.

NOT REVERSIBLE IN THE WAY THAT MATTERS. `downgrade` puts the columns back,
because a migration that cannot be stepped down is a migration that traps an
environment. It does not put the data back, and nothing should want it to.

PARENT. The revision graph has ten heads; this one is chained to
`svst5_faults`, which is the revision the platform database is actually
stamped at and the only head whose ancestry contains
`a9b7c2e8f4d1_add_runtime_exceptions`, the migration that created the table
and these columns. Dropping a column on a branch that never created it would
fail on exactly the environments that matter.

Revision ID: rx0918_drop_crash_payload
Revises: svst5_faults
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "rx0918_drop_crash_payload"
down_revision = "svst5_faults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The rows are purged before the drop rather than left to it: DROP COLUMN
    # in Postgres only marks the attribute dropped, and the values stay in the
    # heap tuples until something rewrites them. An environment that never
    # vacuums would keep a customer's order on disk behind a column nobody can
    # select. Setting them NULL first means the rewrite that VACUUM eventually
    # does has nothing to carry forward.
    op.execute(
        "UPDATE runtime_exceptions SET request_body = NULL, user_context = NULL "
        "WHERE request_body IS NOT NULL OR user_context IS NOT NULL"
    )
    op.drop_column("runtime_exceptions", "request_body")
    op.drop_column("runtime_exceptions", "user_context")


def downgrade() -> None:
    # The shape comes back; the contents do not, and are not meant to.
    op.add_column("runtime_exceptions", sa.Column("user_context", JSONB(), nullable=True))
    op.add_column("runtime_exceptions", sa.Column("request_body", JSONB(), nullable=True))
