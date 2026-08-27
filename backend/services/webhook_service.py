"""Webhook service — fires webhooks on platform events."""

import hmac
import hashlib
import json
import uuid
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.webhook import Webhook

logger = logging.getLogger(__name__)

# Supported events
EVENTS = [
    "project.created",
    "project.updated",
    "project.archived",
    "generation.started",
    "generation.complete",
    "generation.failed",
    "workflow.instance_started",
    "workflow.instance_completed",
    "workflow.task_assigned",
    "workflow.task_completed",
]


async def fire_event(
    db: AsyncSession,
    project_id: uuid.UUID,
    event: str,
    payload: dict,
) -> int:
    """Fire webhooks for a specific event. Returns number of webhooks triggered."""
    result = await db.execute(
        select(Webhook).where(
            Webhook.project_id == project_id,
            Webhook.is_active.is_(True),
        )
    )
    webhooks = result.scalars().all()

    triggered = 0
    for webhook in webhooks:
        # Check if this webhook subscribes to this event
        events = webhook.events or []
        if events and event not in events and "*" not in events:
            continue

        success = await _deliver_webhook(webhook, event, payload)

        # Update webhook status
        if success:
            webhook.last_triggered_at = datetime.now(timezone.utc)
            webhook.failure_count = 0
            triggered += 1
        else:
            webhook.failure_count = (webhook.failure_count or 0) + 1
            # Disable after 10 consecutive failures
            if webhook.failure_count >= 10:
                webhook.is_active = False
                logger.warning("Webhook %s disabled after 10 failures", webhook.id)

    await db.flush()
    return triggered


async def _deliver_webhook(webhook: Webhook, event: str, payload: dict) -> bool:
    """Deliver a webhook payload to the subscriber URL."""
    body = json.dumps({
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": payload,
    })

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Event": event,
    }

    # Sign the payload if secret is configured
    if webhook.secret:
        signature = hmac.new(
            webhook.secret.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={signature}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook.url, content=body, headers=headers)

        if resp.status_code < 300:
            logger.info("Webhook %s delivered: %s → %s", webhook.id, event, resp.status_code)
            return True
        else:
            logger.warning(
                "Webhook %s failed: %s → %s %s",
                webhook.id, event, resp.status_code, resp.text[:200],
            )
            return False
    except Exception as e:
        logger.error("Webhook %s delivery error: %s", webhook.id, e)
        return False
