import asyncio
import os
from unittest.mock import patch, AsyncMock

import pytest

from services.register_selector import (
    classify_register,
    classify_register_llm,
    list_registers,
    describe_register,
    _coerce_register_name,
)


def test_hr_domain_picks_workday():
    assert classify_register("manage employee leave", "hr") == "workday"


def test_fintech_brief_picks_stripe():
    assert classify_register("track customer invoices and payments", "") == "stripe"


def test_devtools_brief_picks_linear():
    assert classify_register("CI/CD dashboard with deployment logs", "") == "linear"


def test_docs_brief_picks_notion():
    assert classify_register("internal wiki for engineering documentation", "") == "notion"


def test_design_brief_picks_figma():
    assert classify_register("brand guidelines and asset library", "") == "figma"


def test_default_fallback_is_workday():
    assert classify_register("a simple notes app", "") == "workday"


def test_all_registers_listed():
    registers = list_registers()
    assert "workday" in registers
    assert "linear" in registers
    assert "stripe" in registers
    assert "notion" in registers
    assert "figma" in registers


def test_describe_register_returns_string_for_all():
    for r in list_registers():
        assert describe_register(r)


# ---------------------------------------------------------------------------
# LLM classifier — covers the path that wraps the rule-based fallback.
# ---------------------------------------------------------------------------

def _run(coro):
    """Helper: run an async test body without needing pytest-asyncio."""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_llm_classifier_falls_back_to_rules_when_no_api_key(monkeypatch):
    # No API key → no Anthropic call attempted, transparent fall-through.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    chosen = _run(classify_register_llm("manage employee leave", "hr"))
    assert chosen == "workday"  # Same as rule-based test above


def test_llm_classifier_falls_back_when_response_is_garbage(monkeypatch):
    # API key present but the model returns something unparseable → fall back.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    with patch(
        "services.register_selector._call_anthropic",
        new=AsyncMock(return_value="I cannot answer that"),
    ):
        chosen = _run(classify_register_llm("track customer invoices", ""))
    assert chosen == "stripe"  # rule-based caught the keyword


def test_llm_classifier_returns_model_choice_when_valid(monkeypatch):
    # Model returns a valid register name → use it directly, even if the
    # rule-based path would have picked something else.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    # Brief that the rules would map to "workday" (default fallback) — but
    # the model says "linear", which should win.
    with patch(
        "services.register_selector._call_anthropic",
        new=AsyncMock(return_value="linear"),
    ):
        chosen = _run(classify_register_llm("a developer-focused dashboard", ""))
    assert chosen == "linear"


def test_llm_classifier_falls_back_on_api_failure(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    with patch(
        "services.register_selector._call_anthropic",
        new=AsyncMock(side_effect=RuntimeError("auth failed")),
    ):
        chosen = _run(classify_register_llm("brand guidelines", ""))
    assert chosen == "figma"  # rule-based keyword match still wins


def test_llm_classifier_empty_brief_falls_back_immediately(monkeypatch):
    # Don't waste an API call on an empty brief — short-circuit to rules.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    with patch("services.register_selector._call_anthropic") as mock_call:
        chosen = _run(classify_register_llm("", "hr"))
    assert chosen == "workday"
    mock_call.assert_not_called()


@pytest.mark.parametrize("text,expected", [
    ("workday", "workday"),
    ("Linear", "linear"),
    ("  stripe  ", "stripe"),
    ("`figma`", "figma"),
    ("notion.", "notion"),
    ('"default"', "default"),
    ("I think the best register is linear, because…", "linear"),  # extracts first valid token
    ("", None),
    ("nonexistent", None),
    ("kafka", None),
])
def test_coerce_register_name(text, expected):
    assert _coerce_register_name(text) == expected
