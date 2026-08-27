# backend/tests/services/test_vision_evaluator.py
"""Vision evaluator tests use a stubbed Anthropic client so they run offline."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from services.vision_evaluator.evaluator import evaluate_page, EvaluatorContext
from services.vision_evaluator.types import (
    Scores, compute_composite, compute_composite_for_domain,
)


VALID_RESPONSE = json.dumps({
    "scores": {
        "visualPolish": 7, "domainFeel": 6, "informationDensity": 5,
        "componentCoherence": 7, "brandReflection": 6,
    },
    "compositeScore": 6.4,
    "pass": False,
    "topIssues": [],
    "strengths": ["Hero is solid"],
    "designerApprovalRecommended": False,
})


def make_context(**overrides) -> EvaluatorContext:
    base = dict(
        domain="hr", app_name="Leave Management",
        description="manage time off", tone="trustworthy",
        route="/users/list", page_type="list",
        page_role="users come here to find a teammate",
        iteration=0, max_iter=3,
    )
    base.update(overrides)
    return EvaluatorContext(**base)


@pytest.mark.asyncio
async def test_evaluate_page_returns_critique_on_clean_response():
    with patch("services.vision_evaluator.evaluator._call_claude_vision",
               new=AsyncMock(return_value=VALID_RESPONSE)):
        c = await evaluate_page(
            png_bytes=b"\x89PNG\r\n\x1a\n",  # minimal PNG header for the call
            a11y_tree="- Stack 'root'",
            ctx=make_context(),
        )
        assert c.compositeScore == 6.4
        assert c.pass_ is False


@pytest.mark.asyncio
async def test_evaluate_page_retries_once_on_invalid_json():
    bad_then_good = AsyncMock(side_effect=["not json at all", VALID_RESPONSE])
    with patch("services.vision_evaluator.evaluator._call_claude_vision", new=bad_then_good):
        c = await evaluate_page(
            png_bytes=b"\x89PNG\r\n\x1a\n",
            a11y_tree="- Stack",
            ctx=make_context(),
        )
        assert c.compositeScore == 6.4
        assert bad_then_good.call_count == 2


@pytest.mark.asyncio
async def test_evaluate_page_raises_after_two_invalid_responses():
    always_bad = AsyncMock(return_value="still not json")
    with patch("services.vision_evaluator.evaluator._call_claude_vision", new=always_bad):
        with pytest.raises(Exception):
            await evaluate_page(
                png_bytes=b"\x89PNG\r\n\x1a\n",
                a11y_tree="- Stack",
                ctx=make_context(),
            )
        assert always_bad.call_count == 2


def test_composite_for_unknown_domain_falls_back_to_default():
    s = Scores(visualPolish=8, domainFeel=8, informationDensity=8,
               componentCoherence=8, brandReflection=8)
    assert compute_composite_for_domain(s, "unknown") == compute_composite(s)


def test_hr_domain_weights_information_density_higher():
    # 10/10 on info density should be valued more under HR weights than default
    high_density = Scores(visualPolish=5, domainFeel=5, informationDensity=10,
                           componentCoherence=5, brandReflection=5)
    default_score = compute_composite(high_density)
    hr_score = compute_composite_for_domain(high_density, "hr")
    assert hr_score > default_score
