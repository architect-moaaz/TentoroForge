"""AI decide handler — makes boolean decision for then/else branching."""

import json
import logging

from runtime.ai.base import AINodeHandler

logger = logging.getLogger(__name__)


class DecideHandler(AINodeHandler):
    """AI-powered decision: evaluates context and returns a boolean for then/else branching."""

    async def execute(self, config: dict) -> dict:
        ai_context = self.resolver.resolve_string(config.get("aiContext", ""))
        ai_options = config.get("aiOptions", [])
        ai_rules = self.resolver.resolve_string(config.get("aiRules", ""))
        ai_prompt = self.resolver.resolve_string(config.get("aiPrompt", ""))

        options_str = ", ".join(ai_options) if ai_options else "approve, reject"

        system_prompt = (
            "You are a decision-making assistant. Based on the context and rules provided, "
            f"make a decision. Options: [{options_str}]. "
            "Respond with JSON: {\"decision\": true/false, \"confidence\": <0.0-1.0>, \"reasoning\": \"<brief explanation>\"}\n"
            "decision=true means the primary/positive option, false means the secondary/negative option."
        )
        context_parts = []
        if ai_context:
            context_parts.append(f"Context: {ai_context}")
        if ai_rules:
            context_parts.append(f"Rules: {ai_rules}")
        if ai_prompt:
            context_parts.append(f"Additional instructions: {ai_prompt}")
        user_prompt = "\n\n".join(context_parts) or "Make a decision based on available information."

        response = await self._call_llm(system_prompt, user_prompt)
        parsed = self._parse_json_response(response)

        decision = bool(parsed.get("decision", True))
        confidence = float(parsed.get("confidence", 0.8))
        reasoning = parsed.get("reasoning", "")

        return {
            "decision": decision,
            "confidence": confidence,
            "reasoning": reasoning,
            "output": decision,
        }

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "decision": True,
            "confidence": 0.85,
            "reasoning": "Mock decision — defaulting to true",
        })
