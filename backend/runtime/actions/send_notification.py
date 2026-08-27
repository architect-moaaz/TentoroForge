"""Send notification action dispatcher."""

import logging

from runtime.actions.base import ActionDispatcher

logger = logging.getLogger(__name__)


class SendNotificationDispatcher(ActionDispatcher):
    """Creates an in-app notification (logged for now)."""

    async def execute(self, config: dict) -> dict:
        description = self.resolver.resolve_string(config.get("description", ""))
        title = self.resolver.resolve_string(config.get("title", "Workflow Notification"))
        recipient = self.resolver.resolve_string(config.get("recipient", ""))

        logger.info("Notification action — title: %s, description: %s", title, description)

        return {
            "action_type": "send_notification",
            "title": title,
            "description": description,
            "recipient": recipient,
            "result": "sent",
        }
