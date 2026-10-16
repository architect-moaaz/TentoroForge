"""Credit per organisation, and spending limits — the policy the cockpit keeps.

Money is kept in tables, not in a file beside the ledger: the platform runs
on more than one worker, and what an organisation holds has to read the
same from every one of them. A credit entry is signed — an opening balance,
a top-up, an adjustment down, a refund — with the reason and the hand that
made it, so the history IS the balance. A limit is one row per scope and
period; clearing a period deletes its row.

No Postgres enums, no JSONB, Python-side ids: the tables are what the
in-memory test database can hold as they are.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

CREDIT_KINDS = ("opening", "top_up", "adjustment", "refund")


class CreditEntry(Base):
    __tablename__ = "credit_entries"
    __table_args__ = (Index("ix_credit_entries_org_at", "org_id", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    #: Signed: credit in, adjustments and refunds out.
    amount_usd: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SpendLimit(Base):
    __tablename__ = "spend_limits"
    __table_args__ = (UniqueConstraint("scope_kind", "scope_id", "period", name="uq_spend_limit_scope_period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    #: platform | org | user | project
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: "" for the platform; an organisation id; a person's email; an app's short id.
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    period: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_usd: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    set_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
