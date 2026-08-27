"""AI classify handler — classifies input into labels."""

import json
import logging

from runtime.ai.base import AINodeHandler

logger = logging.getLogger(__name__)


class ClassifyHandler(AINodeHandler):
    """Classifies input text into one of the provided labels."""

    async def execute(self, config: dict) -> dict:
        ai_input = self.resolver.resolve_string(config.get("aiInput", ""))
        ai_labels = config.get("aiLabels", [])
        ai_prompt = self.resolver.resolve_string(config.get("aiPrompt", ""))
        threshold = float(config.get("aiThreshold", 0.7))

        labels_str = ", ".join(ai_labels) if ai_labels else "positive, negative, neutral"

        system_prompt = (
            "You are a classification assistant. Classify the input into exactly one of the "
            f"given labels. Labels: [{labels_str}]. "
            "Respond with JSON: {\"label\": \"<label>\", \"confidence\": <0.0-1.0>}"
        )
        user_prompt = f"{ai_prompt}\n\nInput to classify:\n{ai_input}" if ai_prompt else ai_input

        response = await self._call_llm(system_prompt, user_prompt)
        parsed = self._parse_json_response(response)

        label = parsed.get("label", ai_labels[0] if ai_labels else "unknown")
        confidence = float(parsed.get("confidence", 0.8))

        return {
            "label": label,
            "confidence": confidence,
            "meets_threshold": confidence >= threshold,
            "output": label,
        }

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps({"label": "positive", "confidence": 0.85})
