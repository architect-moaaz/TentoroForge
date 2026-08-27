"""Execution logger — records audit trail for every workflow node execution."""

import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from models.node_execution_log import NodeExecutionLog, NodeExecutionStatus

logger = logging.getLogger(__name__)


class ExecutionLogger:
    """Logs start/complete/fail/skip events for workflow node executions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_start(
        self,
        instance_id: uuid.UUID,
        node_id: str,
        node_type: str,
        node_label: str | None,
        input_snapshot: dict | None = None,
    ) -> NodeExecutionLog:
        """Record that a node has started executing."""
        entry = NodeExecutionLog(
            workflow_instance_id=instance_id,
            node_id=node_id,
            node_type=node_type,
            node_label=node_label,
            status=NodeExecutionStatus.started,
            input_snapshot=input_snapshot,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(entry)
        await self.db.flush()
        logger.debug("Node started: %s (%s) in instance %s", node_id, node_type, instance_id)
        return entry

    async def log_complete(
        self,
        log_entry: NodeExecutionLog,
        output_snapshot: dict | None = None,
    ) -> None:
        """Record that a node has completed successfully."""
        now = datetime.now(timezone.utc)
        log_entry.status = NodeExecutionStatus.completed
        log_entry.completed_at = now
        log_entry.output_snapshot = output_snapshot
        if log_entry.started_at:
            delta = now - log_entry.started_at
            log_entry.duration_ms = int(delta.total_seconds() * 1000)
        await self.db.flush()
        logger.debug("Node completed: %s (duration=%sms)", log_entry.node_id, log_entry.duration_ms)

    async def log_failure(
        self,
        log_entry: NodeExecutionLog,
        error_message: str,
    ) -> None:
        """Record that a node has failed."""
        now = datetime.now(timezone.utc)
        log_entry.status = NodeExecutionStatus.failed
        log_entry.completed_at = now
        log_entry.error_message = error_message
        if log_entry.started_at:
            delta = now - log_entry.started_at
            log_entry.duration_ms = int(delta.total_seconds() * 1000)
        await self.db.flush()
        logger.warning("Node failed: %s — %s", log_entry.node_id, error_message)

    async def log_skip(
        self,
        instance_id: uuid.UUID,
        node_id: str,
        node_type: str,
        node_label: str | None,
        reason: str,
    ) -> NodeExecutionLog:
        """Record that a node was skipped."""
        now = datetime.now(timezone.utc)
        entry = NodeExecutionLog(
            workflow_instance_id=instance_id,
            node_id=node_id,
            node_type=node_type,
            node_label=node_label,
            status=NodeExecutionStatus.skipped,
            error_message=reason,
            started_at=now,
            completed_at=now,
            duration_ms=0,
        )
        self.db.add(entry)
        await self.db.flush()
        logger.debug("Node skipped: %s — %s", node_id, reason)
        return entry
