# backend/services/vision_evaluator/__init__.py
from .evaluator import evaluate_page, EvaluatorContext
from .prompt import SYSTEM_PROMPT, build_user_prompt
from .types import (
    Critique, Issue, Scores, PatchOp,
    COMPOSITE_WEIGHTS, compute_composite,
    DOMAIN_COMPOSITE_WEIGHTS, compute_composite_for_domain,
)
from .validator import ValidationError, parse_critique_json

__all__ = [
    "evaluate_page", "EvaluatorContext",
    "Critique", "Issue", "Scores", "PatchOp",
    "COMPOSITE_WEIGHTS", "compute_composite",
    "DOMAIN_COMPOSITE_WEIGHTS", "compute_composite_for_domain",
    "SYSTEM_PROMPT", "build_user_prompt",
    "ValidationError", "parse_critique_json",
]
