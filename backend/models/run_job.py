"""A build or a Smith turn, on record while it runs — one row each.

A build or turn ran as a thread in one API worker and nothing outside that
worker knew of it: a restart left a ledger that was closed as crashed and a
person told to say "carry on" (audit, 2026-11-01). The row is what survives
the process: what was asked, who for and with what ceiling, which worker has
it and when it last said so, and — once the work is in a run that carries on
from the Blueprint's own state — how to carry it on (`resume`). The leader
reads the rows a dead worker left (`services.jobs.recover`).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class RunJob(Base):
    __tablename__ = "run_jobs"
    __table_args__ = (
        Index("ix_run_jobs_status", "status"),
        Index("ix_run_jobs_project_created", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
    )
    #: `build` (the generate endpoint), `turn` (a Smith turn), `handoff` (the Drafts Room's build).
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The request's own arguments, as they came.
    args: Mapped[dict | None] = mapped_column(JSONB)
    #: Who it is for and the most it may spend (`_actor_of`): {"user", "org", "ceiling"}.
    actor: Mapped[dict | None] = mapped_column(JSONB)
    #: queued → waiting (for a build slot) → running → done | failed; a dead
    #: worker's job goes running again where it is resumed, or reported.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    #: How to carry it on from the Blueprint (`_run_dag`'s arguments), once it
    #: is in such a run; None while it is not, and then it cannot be resumed.
    resume: Mapped[dict | None] = mapped_column(JSONB)
    #: `host:pid` of the worker running it, and when that worker took it.
    worker: Mapped[str | None] = mapped_column(String(128))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: How many workers have taken it: 1, and 2 once resumed.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error: Mapped[str | None] = mapped_column(Text)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
