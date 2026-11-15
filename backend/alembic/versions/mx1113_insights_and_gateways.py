"""Join the agent-insights line and the payment-gateways line (#30 and #37, merged 2026-11-13)

Revision ID: mx1113_insights_and_gateways
Revises: pg1030_payment_gateways, ai1022_agent_insights_stream

`ai1022` was written on top of `tp1016`, before the run-jobs, gallery and
gateway migrations landed. Merged into smithv5 that left two heads, and a new
database stopped at `alembic upgrade head`. This migration joins the two lines
and changes nothing. `ai1022` keeps its parent, so a database that already
applied it upgrades the same way as one that did not.
"""
from typing import Sequence, Union

revision: str = "mx1113_insights_and_gateways"
down_revision: Union[str, Sequence[str], None] = ("pg1030_payment_gateways", "ai1022_agent_insights_stream")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
