"""Base AI node handler with LLM call + mock fallback."""

import os
import json
import logging
from abc import ABC, abstractmethod

from runtime.variable_resolver import VariableResolver

logger = logging.getLogger(__name__)


class AINodeHandler(ABC):
    """Abstract base for AI-powered workflow node handlers.

    Calls the Anthropic API if ANTHROPIC_API_KEY is set; otherwise uses
    deterministic mock responses so workflows still complete in dev/test.
    """

    def __init__(self, variables: dict):
        self.variables = variables
        self.resolver = VariableResolver(variables)

    @abstractmethod
    async def execute(self, config: dict) -> dict:
        """Execute the AI node and return output data."""
        ...

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the Anthropic Claude API. Falls back to mock if no API key."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.info("No ANTHROPIC_API_KEY — using mock response")
            return self._mock_response(system_prompt, user_prompt)

        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=api_key)
            message = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return message.content[0].text
        except Exception as e:
            logger.warning("LLM call failed, using mock: %s", e)
            return self._mock_response(system_prompt, user_prompt)

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        """Deterministic mock response for dev/test environments."""
        return json.dumps({"mock": True, "result": "mock_response"})

    def _parse_json_response(self, text: str) -> dict:
        """Try to parse JSON from LLM response, handling markdown code blocks."""
        text = text.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_response": text}
