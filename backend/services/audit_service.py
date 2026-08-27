"""Audit service — log create/update/delete operations for compliance."""

import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from models.audit import AuditLog

logger = logging.getLogger(__name__)


async def audit_log(
    db: AsyncSession,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    changes: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> AuditLog:
    """Create an audit log entry.

    Args:
        db: Database session
        user_id: Who performed the action
        action: What action (create, update, delete, login, logout, etc.)
        resource_type: What was affected (project, org, workflow, rule, etc.)
        resource_id: ID of the affected resource
        changes: Dict of changes (before/after or field changes)
        ip_address: Client IP address
        user_agent: Client user agent string
        request_id: Request correlation ID
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
    )
    db.add(entry)
    await db.flush()

    logger.info(
        "AUDIT: user=%s action=%s resource=%s/%s",
        user_id, action, resource_type, resource_id,
    )
    return entry
