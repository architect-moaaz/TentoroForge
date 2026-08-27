"""Tests for computational_plan.build_computational_plan — the deterministic
short-circuit that bypasses the LLM planner for calculator/converter/etc asks.
"""
from services.computational_plan import (
    build_computational_plan,
    is_computational_classification,
)


class TestShape:
    def test_shape_matches_pipeline_contract(self):
        plan = build_computational_plan("build a calculator", {})
        # These top-level keys are what every downstream stage reads via
        # .get(...) — MUST be present + typed correctly.
        assert plan["entities"] == []
        assert plan["relations"] == []
        assert plan["workflows"] == []
        assert plan["api_routes"] == []
        assert plan["components"] == []
        assert plan["dashboard_widgets"] == []
        assert plan["field_visibility"] == []
        assert plan["capacity_constraints"] == []
        assert plan["structured_brief"] is None

    def test_single_anon_visitor_actor(self):
        plan = build_computational_plan("EMI calculator", {})
        assert len(plan["actors"]) == 1
        actor = plan["actors"][0]
        assert actor["name"] == "visitor"
        assert actor["access"] == "anon"
        assert actor["onboarding"] == "none"

    def test_single_computational_page(self):
        plan = build_computational_plan("build a tip calculator", {})
        assert len(plan["pages"]) == 1
        page = plan["pages"][0]
        assert page["archetype"] == "computational"
        assert page["route"] == "/"
        assert page["shell"] is True
        assert page["features"] == []

    def test_prompt_preserved_in_description(self):
        raw = "Given loan principal, annual rate, and tenure, compute monthly EMI."
        plan = build_computational_plan(raw, {})
        # The description carries the ORIGINAL prompt so the downstream
        # page-schema author has the formula intent to translate.
        assert plan["pages"][0]["description"] == raw

    def test_meta_carries_source_and_archetype(self):
        plan = build_computational_plan(
            "calculator", {"matched": ["calculator"]},
        )
        assert plan["meta"]["source"] == "computational_plan_builder"
        assert plan["meta"]["archetype"] == "computational"
        assert plan["meta"]["matched_tokens"] == ["calculator"]

    def test_navigation_is_chromeless(self):
        # A single-page tool doesn't need sidebar/topbar chrome; the shell
        # composer reads navigation.type=="none" to skip nav rendering.
        plan = build_computational_plan("BMI calculator", {})
        assert plan["navigation"]["type"] == "none"
        assert plan["navigation"]["initial"] == "/"
        assert plan["navigation"]["items"] == []


class TestPageNaming:
    def test_qualifier_before_kind_word(self):
        plan = build_computational_plan(
            "monthly EMI calculator app for loans",
            {"matched": ["calculator"]},
        )
        # "EMI" is the noun-ish qualifier immediately before "calculator"
        assert "EMI" in plan["pages"][0]["name"]
        assert "Calculator" in plan["pages"][0]["name"]

    def test_matched_token_alone_when_no_qualifier(self):
        plan = build_computational_plan(
            "build me a calculator",
            {"matched": ["calculator"]},
        )
        # Only generic articles precede — fall back to the matched token
        assert plan["pages"][0]["name"] == "Calculator"

    def test_currency_converter_multiword(self):
        plan = build_computational_plan(
            "a currency converter for USD/EUR",
            {"matched": ["currency converter"]},
        )
        # Multi-word matched token is title-cased intact
        assert "Currency Converter" in plan["pages"][0]["name"]

    def test_fallback_when_no_matched(self):
        # No classification hint → use first meaningful words of the prompt
        plan = build_computational_plan("Budget planner tool", {})
        assert plan["pages"][0]["name"]  # non-empty
        assert "Budget" in plan["pages"][0]["name"]

    def test_empty_prompt_safe_fallback(self):
        plan = build_computational_plan("", {})
        assert plan["pages"][0]["name"]  # still produces a name
        assert plan["pages"][0]["description"]  # still has a description


class TestClassificationGate:
    def test_true_for_computational_shape(self):
        assert is_computational_classification({"shape": "computational"}) is True

    def test_false_for_other_shapes(self):
        assert is_computational_classification({"shape": "crud"}) is False
        assert is_computational_classification({"shape": "interactive"}) is False
        assert is_computational_classification({"shape": "unclear"}) is False

    def test_safe_for_none_or_non_dict(self):
        assert is_computational_classification(None) is False
        assert is_computational_classification("computational") is False
        assert is_computational_classification({}) is False
