"""HTTP call action dispatcher — makes HTTP requests via httpx."""

import logging

from runtime.actions.base import ActionDispatcher

logger = logging.getLogger(__name__)


class HttpCallDispatcher(ActionDispatcher):
    """Makes an async HTTP request based on node config."""

    async def execute(self, config: dict) -> dict:
        import httpx

        url = self.resolver.resolve_string(config.get("url", ""))
        method = config.get("method", "GET").upper()
        headers = self.resolver.resolve_dict(config.get("headers", {}))
        body = self.resolver.resolve_dict(config.get("body", {})) if config.get("body") else None

        logger.info("HTTP %s %s", method, url)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=body,
            )

        logger.info("HTTP response: %s %s", response.status_code, url)

        # Try to parse JSON response, fall back to text
        try:
            response_body = response.json()
        except Exception:
            response_body = response.text[:2000]

        return {
            "action_type": "http_call",
            "status_code": response.status_code,
            "response": response_body,
            "result": "success" if response.is_success else "error",
        }
