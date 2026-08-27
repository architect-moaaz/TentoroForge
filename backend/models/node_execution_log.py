"""Node execution log — audit trail for every workflow node execution."""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
    Index,
    Enum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class NodeExecutionStatus(str, PyEnum):
    started = "started"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class NodeExecutionLog(Base):
    __tablename__ = "node_execution_logs"
    __table_args__ = (
        Index("ix_nel_instance", "workflow_instance_id"),
        Index("ix_nel_node_id", "node_id"),
        Index("ix_nel_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    node_type: Mapped[str] = mapped_column(String(100), nullable=False)
    node_label: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[NodeExecutionStatus] = mapped_column(
        Enum(NodeExecutionStatus, name="node_execution_status"),
        nullable=False,
    )
    input_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    output_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    workflow_instance = relationship("WorkflowInstance", backref="execution_logs")
