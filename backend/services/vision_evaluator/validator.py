# backend/services/vision_evaluator/validator.py
"""Strict JSON parsing + Pydantic validation for vision evaluator responses."""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .types import Critique


class ValidationError(Exception):
    """Raised when a model response can't be parsed into a Critique."""


def parse_critique_json(text: str) -> Critique:
    """Parse a JSON string into a Critique, raising ValidationError on any
    problem. The model is expected to emit strict JSON; if it doesn't, the
    caller can retry with a fixup prompt.

    Tolerates a few common LLM emission patterns the system prompt asks the
    model to avoid but Sonnet sometimes emits anyway:
      - leading/trailing markdown code fences (```json ... ```)
      - leading/trailing prose (we slice from first `{` to last `}`)
    """
    cleaned = _strip_fences_and_prose(text)
    try:
        payload: Any = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValidationError(f"invalid JSON: {e}") from e
    try:
        return Critique.model_validate(payload)
    except PydanticValidationError as e:
        raise ValidationError(f"shape mismatch: {e}") from e


def _strip_fences_and_prose(text: str) -> str:
    """Best-effort trim of markdown fences and surrounding prose around a
    JSON object."""
    s = (text or "").strip()
    # Strip leading ```json or ``` line
    if s.startswith("```"):
        first_newline = s.find("\n")
        if first_newline != -1:
            s = s[first_newline + 1 :]
        # Strip trailing ``` if present
        if s.rstrip().endswith("```"):
            s = s.rstrip()[: -3].rstrip()
    # If the model added a header line before the JSON, slice from first `{`
    # to last `}`. This is safe because the Critique payload is always a
    # single top-level object.
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end > start:
        s = s[start : end + 1]
    return s
