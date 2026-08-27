"""AI generate handler — generates text content."""

import json
import logging

from runtime.ai.base import AINodeHandler

logger = logging.getLogger(__name__)


class GenerateHandler(AINodeHandler):
    """Generates text content based on a prompt and tone."""

    async def execute(self, config: dict) -> dict:
        ai_prompt = self.resolver.resolve_string(config.get("aiPrompt", ""))
        ai_tone = config.get("aiTone", "professional")
        ai_input = self.resolver.resolve_string(config.get("aiInput", ""))

        system_prompt = (
            f"You are a content generation assistant. Write in a {ai_tone} tone. "
            "Respond with JSON: {\"generated_text\": \"<your generated content>\"}"
        )
        user_prompt = ai_prompt
        if ai_input:
            user_prompt = f"{ai_prompt}\n\nContext:\n{ai_input}" if ai_prompt else ai_input

        response = await self._call_llm(system_prompt, user_prompt or "Generate content.")
        parsed = self._parse_json_response(response)

        generated_text = parsed.get("generated_text", parsed.get("raw_response", ""))

        return {
            "generated_text": generated_text,
            "tone": ai_tone,
            "output": generated_text,
        }

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "generated_text": "This is mock-generated content for testing purposes."
        })
