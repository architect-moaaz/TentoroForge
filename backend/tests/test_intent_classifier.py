"""Tests for Smith's intent classifier + scoped tool subsets (Phase 0).

Two pieces:
  1. ``classify_intent`` — one structured LLM call at Smith turn ingress.
     Returns ``Intent`` with (intent, domain, target, tools, confidence).
     The test suite stubs the LLM boundary so no live calls happen.
  2. ``TOOL_SUBSETS`` — intent → allowed-tool-names map. Filters what
     tools the ReAct loop sees when confidence is high.

Failure modes covered:
  * Garbage LLM output falls back safely to full catalog (confidence 0).
  * Unknown intent falls back to ``unclear`` (no scoping).
  * Every intent value maps to a tool subset (or explicit None).
  * Every tool in every subset exists in the real TOOL_CATALOG.
"""

from __future__ import annotations

import pytest

from services.intent_classifier import (
    INTENTS,
    Intent,
    TOOL_SUBSETS,
    classify_intent,
)


# --------------------------------------------------------------------------- #
# Contract shape                                                              #
# --------------------------------------------------------------------------- #

class TestContract:
    def test_every_intent_has_a_subset_or_explicit_none(self):
        """Every declared intent maps to a list or None (=full catalog)."""
        for i in INTENTS:
            assert i in TOOL_SUBSETS, f"intent {i!r} has no subset entry"
            v = TOOL_SUBSETS[i]
            assert v is None or isinstance(v, list), f"{i!r} subset shape"

    def test_every_subset_tool_exists_in_catalog(self):
        """No subset can name a tool that doesn't exist. Guards against
        typos that would silently make the intent fall back to unclear."""
        from services.smith_tools import TOOL_CATALOG
        real = {t["name"] for t in TOOL_CATALOG}
        for intent, subset in TOOL_SUBSETS.items():
            if subset is None:
                continue
            missing = [t for t in subset if t not in real]
            assert not missing, f"{intent!r} names missing tools: {missing}"

    def test_answer_and_ask_user_in_every_actionable_subset(self):
        """Every scoped intent MUST include ``answer`` and ``ask_user`` so
        Smith can terminate the loop even when constrained."""
        for intent, subset in TOOL_SUBSETS.items():
            if subset is None:
                continue
            assert "answer" in subset, f"{intent!r} missing answer"
            assert "ask_user" in subset, f"{intent!r} missing ask_user"


# --------------------------------------------------------------------------- #
# classify_intent — LLM-boundary tests                                        #
# --------------------------------------------------------------------------- #

def _stub_query(payload: str):
    """Build a query_fn that returns the given payload verbatim."""
    def _q(system_prompt: str, user_prompt: str) -> str:
        return payload
    return _q


class TestClassifyIntent:
    def test_valid_add_page_json_parses(self):
        payload = (
            '{"intent":"add_page","domain":"page","target":"Pricing",'
            '"confidence":0.92}'
        )
        r = classify_intent(
            "add a new page called Pricing",
            query_fn=_stub_query(payload),
        )
        assert isinstance(r, Intent)
        assert r.intent == "add_page"
        assert r.domain == "page"
        assert r.target == "Pricing"
        assert 0.9 < r.confidence <= 1.0
        # Tools are DERIVED from the intent, not from the LLM output.
        assert r.tools == TOOL_SUBSETS["add_page"]

    def test_unknown_intent_falls_back_to_unclear(self):
        payload = '{"intent":"defenestrate","domain":"page","confidence":0.9}'
        r = classify_intent("wat", query_fn=_stub_query(payload))
        assert r.intent == "unclear"
        assert r.tools is None  # unclear => no scoping => full catalog

    def test_garbage_output_falls_back_to_unclear_with_zero_confidence(self):
        r = classify_intent("hi", query_fn=_stub_query("not json"))
        assert r.intent == "unclear"
        assert r.confidence == 0.0
        assert r.tools is None

    def test_low_confidence_yields_no_scoping(self):
        """LLM says add_page but with 0.3 confidence — we must NOT scope
        the tool set to add_page's tiny catalog, or an ambiguous ask
        would be locked into a wrong-intent tool subset."""
        payload = (
            '{"intent":"add_page","domain":"page","target":null,'
            '"confidence":0.3}'
        )
        r = classify_intent("do the thing", query_fn=_stub_query(payload))
        assert r.intent == "add_page"
        # But tools stays None because confidence is below the scoping floor.
        assert r.tools is None

    def test_high_confidence_scopes_the_tools(self):
        payload = (
            '{"intent":"edit_page","domain":"page","target":"/candidates",'
            '"confidence":0.85}'
        )
        r = classify_intent(
            "change the title on candidates page",
            query_fn=_stub_query(payload),
        )
        assert r.intent == "edit_page"
        assert r.tools == TOOL_SUBSETS["edit_page"]
        assert "edit_page" in r.tools
        # And critically: does NOT contain add_page (wrong intent).
        assert "add_page" not in r.tools

    def test_chat_intent_scopes_to_answer_and_ask_user_only(self):
        payload = '{"intent":"chat","domain":"meta","confidence":0.99}'
        r = classify_intent("hey", query_fn=_stub_query(payload))
        assert r.tools is not None
        # Chat means: answer terminal, optionally ask_user. Nothing else.
        assert set(r.tools) <= {"answer", "ask_user", "recall"}

    def test_target_is_optional(self):
        payload = (
            '{"intent":"add_page","domain":"page","target":null,'
            '"confidence":0.85}'
        )
        r = classify_intent("add a page", query_fn=_stub_query(payload))
        assert r.target is None

    def test_confidence_clamped_to_0_1(self):
        payload = '{"intent":"chat","domain":"meta","confidence":1.7}'
        r = classify_intent("hi", query_fn=_stub_query(payload))
        assert r.confidence == 1.0

    def test_negative_confidence_clamped(self):
        payload = '{"intent":"chat","domain":"meta","confidence":-0.5}'
        r = classify_intent("hi", query_fn=_stub_query(payload))
        assert r.confidence == 0.0


# --------------------------------------------------------------------------- #
# Deploy / feature / remove / query — key intent tool selection               #
# --------------------------------------------------------------------------- #

class TestKeyIntentSubsets:
    def test_deploy_subset_has_publish(self):
        assert "publish" in TOOL_SUBSETS["deploy"]

    def test_feature_subset_has_plan_and_apply(self):
        assert "plan_and_apply" in TOOL_SUBSETS["feature"]

    def test_remove_subset_has_remove_page(self):
        assert "remove_page" in TOOL_SUBSETS["remove"]

    def test_query_subset_has_list_and_find_tools(self):
        s = TOOL_SUBSETS["query"]
        assert "list_pages" in s
        assert "find_resources" in s

    def test_add_field_subset_can_edit_pages_and_wire_forms(self):
        s = TOOL_SUBSETS["add_field"]
        assert "edit_page" in s
        assert "wire_form_to_workflow" in s
