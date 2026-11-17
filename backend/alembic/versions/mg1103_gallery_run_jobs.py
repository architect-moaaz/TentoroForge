"""join the template gallery (component-fixes) and run jobs (smithv5) heads

Both branched from tp1016_test_and_production; merging smithv5 into
component-fixes left two heads, and `alembic upgrade head` refuses two.

Revision ID: mg1103_gallery_run_jobs
Revises: tg1017_template_gallery, rj1101_run_jobs
Create Date: 2026-11-03
"""
from typing import Sequence, Union


revision: str = "mg1103_gallery_run_jobs"
down_revision: Union[str, None] = ("tg1017_template_gallery", "rj1101_run_jobs")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
