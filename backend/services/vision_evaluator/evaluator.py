# backend/services/vision_evaluator/evaluator.py
"""High-level evaluate_page() — wraps the Anthropic vision call + validation +
one retry on parse failure."""
from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass

from services.llm_client import AsyncAnthropic  # LangGraph migration (LG-1)

from .prompt import SYSTEM_PROMPT, build_user_prompt
from .types import Critique
from .validator import ValidationError, parse_critique_json


logger = logging.getLogger(__name__)


_MODEL = os.getenv("VISION_EVALUATOR_MODEL", "claude-sonnet-4-5-20250929")
_MAX_TOKENS = 4096


@dataclass
class EvaluatorContext:
    domain: str
    app_name: str
    description: str
    tone: str
    route: str
    page_type: str
    page_role: str
    iteration: int = 0
    max_iter: int = 3


async def _call_claude_vision(*, png_bytes: bytes, a11y_tree: str, ctx: EvaluatorContext) -> str:
    """Single Claude vision call returning raw response text. Tested by mocking
    this function — real network access only happens when not patched."""
    client = AsyncAnthropic()
    user_prompt = build_user_prompt(
        domain=ctx.domain, app_name=ctx.app_name, description=ctx.description,
        tone=ctx.tone, route=ctx.route, page_type=ctx.page_type, page_role=ctx.page_role,
        iteration=ctx.iteration, max_iter=ctx.max_iter,
    )
    message = await client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(png_bytes).decode("ascii"),
                }},
                {"type": "text", "text": f"{user_prompt}\n\nACCESSIBILITY TREE:\n{a11y_tree}"},
            ],
        }],
    )
    parts = []
    for block in message.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)


async def evaluate_page(*, png_bytes: bytes, a11y_tree: str, ctx: EvaluatorContext) -> Critique:
    """Public entry point — call the vision model and parse the response.

    On the first invalid response, retry once with a fix-up message appended.
    On the second failure, raise ValidationError so the caller can decide
    whether to skip this page or abort the loop."""
    raw = await _call_claude_vision(png_bytes=png_bytes, a11y_tree=a11y_tree, ctx=ctx)
    try:
        return parse_critique_json(raw)
    except ValidationError as first_err:
        logger.warning("vision evaluator: first response invalid (%s); retrying once", first_err)
        raw_retry = await _call_claude_vision(png_bytes=png_bytes, a11y_tree=a11y_tree, ctx=ctx)
        return parse_critique_json(raw_retry)
