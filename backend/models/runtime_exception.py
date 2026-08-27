"""Runtime exception model — the ledger of errors captured from generated
apps that Smith's self-healing loop reads from.

A runtime exception is anything the generated app catches at runtime:
workflow node crash, unhandled server route, page-render error. The
generated app POSTs each occurrence to Forge, we dedup on
(project, message, source_file, source_line), and the first occurrence
kicks off a Smith turn that tries to fix the offending code.

Status flow::

    open  --(self_heal picks it up)-->  in_progress
                                        |
    in_progress  --(smith terminates with answer + edits)-->  resolved
    in_progress  --(3 failed attempts)-->  unresolvable
    open|in_progress  --(user dismisses in UI)-->  dismissed
"""
import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class RuntimeExceptionKind(str, PyEnum):
    workflow = "workflow"
    api_route = "api_route"
    page_render = "page_render"
    unhandled = "unhandled"


class RuntimeExceptionStatus(str, PyEnum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    unresolvable = "unresolvable"
    dismissed = "dismissed"


class RuntimeException(Base):
    __tablename__ = "runtime_exceptions"
    __table_args__ = (
        UniqueConstraint("project_id", "dedup_key", name="uq_runtime_exc_dedup"),
        Index("ix_runtime_exc_project_status", "project_id", "status"),
        Index("ix_runtime_exc_last_seen", "last_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    kind: Mapped[RuntimeExceptionKind] = mapped_column(
        Enum(RuntimeExceptionKind, name="runtime_exception_kind"),
        nullable=False,
    )

    # The natural-language error the generated app captured. Kept verbatim
    # so Smith can pattern-match against it when synthesizing his prompt.
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stack: Mapped[str | None] = mapped_column(Text)

    # Locators — where the crash happened. Not all fields apply to every
    # kind; workflow crashes fill workflow_id + node_id, api_route crashes
    # fill request_url + request_method, page crashes fill page_route.
    source_file: Mapped[str | None] = mapped_column(String(512))
    source_line: Mapped[int | None] = mapped_column(Integer)
    workflow_id: Mapped[str | None] = mapped_column(String(255))
    node_id: Mapped[str | None] = mapped_column(String(255))
    page_route: Mapped[str | None] = mapped_column(String(512))
    request_url: Mapped[str | None] = mapped_column(String(2048))
    request_method: Mapped[str | None] = mapped_column(String(16))
    request_body: Mapped[dict | None] = mapped_column(JSONB)
    user_context: Mapped[dict | None] = mapped_column(JSONB)

    # Dedup — the hash the ingest endpoint computes from (kind, message,
    # source_file, source_line). Constrained UNIQUE per project so a repeat
    # crash bumps `occurrence_count` instead of creating a new row.
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    # Self-healing state.
    status: Mapped[RuntimeExceptionStatus] = mapped_column(
        Enum(RuntimeExceptionStatus, name="runtime_exception_status"),
        default=RuntimeExceptionStatus.open,
        nullable=False,
    )
    heal_attempts: Mapped[int] = mapped_column(Integer, default=0)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_commit: Mapped[str | None] = mapped_column(String(64))
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    smith_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
    )

    # Relationships
    project = relationship("Project")
