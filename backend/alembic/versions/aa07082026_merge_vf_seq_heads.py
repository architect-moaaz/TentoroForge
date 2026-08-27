"""Merge V&F 2.0 head with component-fixes conversations_seq nullable head.

Two branches converged on 2026-08-07:

- ``02b5f1d84c52`` — merge of conversation_seq + mcp_servers heads (from
  the mcp-tool-node line, arrived via the V&F 2.0 M1-M3 landing).
- ``e7f1a9c2b8d0`` — conversations.seq made nullable (from
  component-fixes: `55983c37a554` → `e7f1a9c2b8d0`).

Neither modifies the other's tables. Empty upgrade/downgrade — pure
graph merge so alembic upgrade head has a single target again.
"""
from alembic import op  # noqa: F401


# revision identifiers, used by Alembic.
revision = "aa07082026"
down_revision = ("02b5f1d84c52", "e7f1a9c2b8d0")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
