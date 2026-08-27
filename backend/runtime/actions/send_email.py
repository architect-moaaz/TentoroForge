"""Send email action dispatcher."""

import logging

from runtime.actions.base import ActionDispatcher

logger = logging.getLogger(__name__)


class SendEmailDispatcher(ActionDispatcher):
    """Resolves email fields and logs the dispatch (actual sending is integration-dependent)."""

    async def execute(self, config: dict) -> dict:
        to = self.resolver.resolve_string(config.get("to", ""))
        subject = self.resolver.resolve_string(config.get("subject", ""))
        template = self.resolver.resolve_string(config.get("template", ""))
        body = self.resolver.resolve_string(config.get("body", ""))

        logger.info("Email action — to: %s, subject: %s", to, subject)

        return {
            "action_type": "send_email",
            "to": to,
            "subject": subject,
            "template": template,
            "body": body,
            "result": "sent",
        }
