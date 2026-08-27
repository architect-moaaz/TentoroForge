"""Custom action dispatcher — generic placeholder for user-defined actions."""

import logging

from runtime.actions.base import ActionDispatcher

logger = logging.getLogger(__name__)


class CustomActionDispatcher(ActionDispatcher):
    """Executes a custom action — logs description and returns success."""

    async def execute(self, config: dict) -> dict:
        description = self.resolver.resolve_string(
            config.get("description", "Custom action")
        )
        logger.info("Custom action executed: %s", description)
        return {
            "action_type": "custom",
            "description": description,
            "result": "success",
        }
