"""Wire-in tests for Spec D Wave 5 — LLM name classifier fallback in
services.figma_name_classifier.classify_with_llm.
"""
from __future__ import annotations

import json

import pytest

from services import figma_llm_ctx, figma_name_classifier


@pytest.fixture(autouse=True)
def _clean_ctx(monkeypatch):
    figma_llm_ctx.reset_figma_llm_context()
    monkeypatch.delenv("FORGE_FIGMA_LLM", raising=False)
    yield
    figma_llm_ctx.reset_figma_llm_context()


class TestKeywordAlwaysWinsForKnownNames:
    def test_heading_keyword_result_preserved(self):
        # Keyword classifier returns ("Heading", {"level": 4}). The
        # LLM MUST NOT interfere with known names — even when enabled.
        r = figma_name_classifier.classify_with_llm("Heading 4", "TEXT")
        assert r == ("Heading", {"level": 4})

    def test_button_keyword_result_preserved(self):
        r = figma_name_classifier.classify_with_llm("Button", "INSTANCE")
        assert r == ("Button", {})


class TestUnknownNameFallsThroughToBox:
    def test_flag_off_returns_box(self):
        r = figma_name_classifier.classify_with_llm(
            "Payment summary tile", "FRAME",
        )
        assert r == ("Box", {})

    def test_flag_on_empty_registry_returns_box(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")
        r = figma_name_classifier.classify_with_llm(
            "Payment summary tile", "FRAME",
        )
        assert r == ("Box", {})


class TestLLMPathFires:
    def test_llm_registered_component_wins(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")

        def _fake_q(_s, _u):
            return json.dumps({"component": "StatCard", "confidence": 0.9})

        figma_llm_ctx.set_figma_llm_context(
            component_registry=["StatCard", "Card"],
            name_query_fn=_fake_q,
        )
        # Unknown name → keyword returns Box → LLM picks StatCard from
        # the registry.
        r = figma_name_classifier.classify_with_llm(
            "Revenue tile", "FRAME",
        )
        assert r == ("StatCard", {})

    def test_llm_off_registry_falls_back_to_box(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")

        def _fake_q(_s, _u):
            return json.dumps({
                "component": "SomethingMadeUp", "confidence": 0.9,
            })

        figma_llm_ctx.set_figma_llm_context(
            component_registry=["Card", "Button"],
            name_query_fn=_fake_q,
        )
        # LLM invents a component → registry-safety inside
        # classify_figma_name_llm downgrades to "Box" → wrapper returns
        # keyword's original Box.
        r = figma_name_classifier.classify_with_llm(
            "Alien widget", "FRAME",
        )
        assert r == ("Box", {})

    def test_llm_raises_falls_through_to_box(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")

        def _boom(_s, _u):
            raise RuntimeError("boom")

        figma_llm_ctx.set_figma_llm_context(
            component_registry=["Card"],
            name_query_fn=_boom,
        )
        r = figma_name_classifier.classify_with_llm(
            "Unknown thing", "FRAME",
        )
        assert r == ("Box", {})

    def test_llm_returns_box_leaves_box(self, monkeypatch):
        # LLM says "Box" (its fallback marker) — wrapper returns keyword's Box.
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")

        def _fake_q(_s, _u):
            return json.dumps({"component": "Box", "confidence": 0.3})

        figma_llm_ctx.set_figma_llm_context(
            component_registry=["Card"],
            name_query_fn=_fake_q,
        )
        r = figma_name_classifier.classify_with_llm(
            "Random ambiguous name", "FRAME",
        )
        assert r == ("Box", {})


class TestPassesNeighbors:
    def test_neighbors_are_forwarded(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")
        captured = {}

        def _fake_q(_s, user):
            captured["user"] = user
            return json.dumps({"component": "Card", "confidence": 0.9})

        figma_llm_ctx.set_figma_llm_context(
            component_registry=["Card"],
            name_query_fn=_fake_q,
        )
        r = figma_name_classifier.classify_with_llm(
            "Weird thing", "FRAME",
            neighbors=["Total", "Chart"],
        )
        assert r == ("Card", {})
        assert '"Total"' in captured["user"]
        assert '"Chart"' in captured["user"]
