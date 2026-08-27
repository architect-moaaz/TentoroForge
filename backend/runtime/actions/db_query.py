"""DB query action dispatcher — logs query for safety (read-only in runtime)."""

import logging

from runtime.actions.base import ActionDispatcher

logger = logging.getLogger(__name__)


class DbQueryDispatcher(ActionDispatcher):
    """Logs a DB query action. Actual execution is logged for audit/safety."""

    async def execute(self, config: dict) -> dict:
        model = self.resolver.resolve_string(config.get("model", ""))
        query = self.resolver.resolve_string(config.get("query", ""))
        description = self.resolver.resolve_string(config.get("description", ""))

        logger.info("DB query action — model: %s, query: %s", model, query)

        return {
            "action_type": "db_query",
            "model": model,
            "query": query,
            "description": description,
            "result": "logged",
        }
