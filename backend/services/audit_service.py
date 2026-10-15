"""Audit service — log create/update/delete operations for compliance."""

import uuid
import logging
from typing import Any

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
    *,
    actor_user_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
) -> AuditLog:
    """Create an audit log entry.

    Args:
        db: Database session
        user_id: Who performed the action, as the application saw it
        action: What action (create, update, delete, login, logout, etc.)
        resource_type: What was affected (project, org, workflow, rule, etc.)
        resource_id: ID of the affected resource
        changes: Dict of changes (before/after or field changes)
        ip_address: Client IP address
        user_agent: Client user agent string
        request_id: Request correlation ID
        actor_user_id: Whose hand it really was — the super admin behind an
            impersonated request; `user_id` itself otherwise
        org_id: The organisation the action concerned, for its admins' trail
    """
    entry = AuditLog(
        user_id=user_id,
        actor_user_id=actor_user_id if actor_user_id is not None else user_id,
        org_id=org_id,
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
        "AUDIT: user=%s actor=%s action=%s resource=%s/%s",
        user_id, entry.actor_user_id, action, resource_type, resource_id,
    )
    return entry


async def audit_request(
    request: Any,
    db: AsyncSession,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    changes: dict | None = None,
    org_id: uuid.UUID | None = None,
) -> AuditLog:
    """An audit row for the request in hand: the person it is served as, the
    actor behind it (`get_current_user` leaves both on `request.state`), and
    the request's address, agent and id."""
    state = getattr(request, "state", None)
    user = getattr(state, "user", None)
    actor = getattr(state, "actor", None) or user
    client = getattr(request, "client", None)
    return await audit_log(
        db,
        getattr(user, "id", None),
        action,
        resource_type,
        resource_id,
        changes,
        ip_address=getattr(client, "host", None),
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
        request_id=getattr(state, "request_id", None),
        actor_user_id=getattr(actor, "id", None),
        org_id=org_id if org_id is not None else getattr(state, "org_id", None),
    )
