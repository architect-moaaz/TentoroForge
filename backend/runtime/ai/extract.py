"""AI extract handler — extracts structured fields from input."""

import json
import logging

from runtime.ai.base import AINodeHandler

logger = logging.getLogger(__name__)


class ExtractHandler(AINodeHandler):
    """Extracts structured fields from input text."""

    async def execute(self, config: dict) -> dict:
        ai_input = self.resolver.resolve_string(config.get("aiInput", ""))
        ai_fields = config.get("aiExtractFields", [])
        ai_prompt = self.resolver.resolve_string(config.get("aiPrompt", ""))

        fields_str = ", ".join(ai_fields) if ai_fields else "name, email, phone"

        system_prompt = (
            "You are a data extraction assistant. Extract the following fields from the input: "
            f"[{fields_str}]. "
            "Respond with JSON containing the extracted fields. Use null for fields not found."
        )
        user_prompt = f"{ai_prompt}\n\nInput:\n{ai_input}" if ai_prompt else ai_input

        response = await self._call_llm(system_prompt, user_prompt)
        parsed = self._parse_json_response(response)

        return {
            "extracted_fields": parsed,
            "output": parsed,
        }

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps({"name": "Mock User", "email": "mock@example.com"})
