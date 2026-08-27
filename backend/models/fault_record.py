"""SV-STRICT-5 — one row per fault observed across the lifetime of a project.

Persists every fault self-verify produces (runtime AND deterministic
promise-gate faults) so the pipeline can compound-learn from its own
runs:

  * Which fault signatures dominate for which archetypes?
  * Which auto-fixes actually stick vs regress?
  * Which components (button / form / list) fault most often?
  * Which planner phrasings correlate with faults downstream?

No consumer for this data yet — Slice 5 is the substrate. Analytics
land on top later. The columns are chosen to serve those future
questions without needing a second migration.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class FaultRecord(Base):
    __tablename__ = "fault_records"
    __table_args__ = (
        # Time-range queries per project (dashboard, recent-faults view).
        Index("fault_records_project_created_idx",
              "project_id", "created_at"),
        # Signature-frequency analytics per project (which faults dominate?).
        Index("fault_records_project_signature_idx",
              "project_id", "signature"),
        # Cross-project signature counts (fleet-wide baseline).
        Index("fault_records_signature_idx", "signature"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("verify_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Classifier output (fault_classifier.FaultSignature enum value).
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    # W-slot the fault falsifies (what/who/where/when/how/why).
    w_slot: Mapped[str] = mapped_column(String(8), nullable=False)

    # Join keys — enable "same component, faults over time" queries.
    component_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    component_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    route: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Which app-state produced this fault. Same hash → same generation;
    # a fault reappearing with a NEW hash means the fix didn't stick
    # even after regeneration.
    generation_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Compact evidence + rendered narrative for the fault-log view.
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    narrative: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Fix outcome — updated by _run_smith_rounds if a fix runs.
    fix_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    # None = not yet re-verified. True = fault not in next round.
    # False = fault reappeared even after fix.
    fix_stuck: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
