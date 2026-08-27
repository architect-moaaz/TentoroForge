"""Wire-in tests for Spec D Wave 5 — LLM nav-icon fallback in
services.nav_icon_map.icon_for_with_llm.
"""
from __future__ import annotations

import json

import pytest

from services import figma_llm_ctx, nav_icon_map


@pytest.fixture(autouse=True)
def _clean_ctx(monkeypatch):
    figma_llm_ctx.reset_figma_llm_context()
    monkeypatch.delenv("FORGE_FIGMA_LLM", raising=False)
    yield
    figma_llm_ctx.reset_figma_llm_context()


class TestKeywordAlwaysWinsForKnownLabels:
    def test_users_label_stays_user_icon(self):
        # Keyword classifier returns "user"; LLM MUST NOT override.
        assert nav_icon_map.icon_for_with_llm("Candidates") == "user"

    def test_analytics_label_stays_bar_chart_icon(self):
        assert nav_icon_map.icon_for_with_llm("Analytics") == "bar-chart"

    def test_flag_off_returns_keyword_for_unknown(self):
        # No flag → falls back to keyword "folder".
        assert nav_icon_map.icon_for_with_llm("Widgets") == "folder"


class TestLLMPathFires:
    def test_llm_pascal_result_gets_kebab_lowercased(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")

        def _fake_q(_s, _u):
            return json.dumps({"icon": "BarChart", "confidence": 0.9})

        figma_llm_ctx.set_figma_llm_context(nav_icon_query_fn=_fake_q)
        # Unknown label ("Widgets") → keyword returned "folder" → LLM
        # picks "BarChart" from the closed Lucide set → normalized to
        # "bar-chart" so the runtime sees the historical shape.
        assert nav_icon_map.icon_for_with_llm("Widgets") == "bar-chart"

    def test_llm_off_registry_falls_back_to_folder(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")

        def _fake_q(_s, _u):
            # Invented icon name not in LUCIDE_ICON_SET.
            return json.dumps({"icon": "MadeUpIcon", "confidence": 0.9})

        figma_llm_ctx.set_figma_llm_context(nav_icon_query_fn=_fake_q)
        # Registry-safety inside choose_nav_icon_llm downgrades to
        # "Folder" → wire returns keyword "folder".
        assert nav_icon_map.icon_for_with_llm("Widgets") == "folder"

    def test_llm_returns_folder_leaves_folder(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")

        def _fake_q(_s, _u):
            return json.dumps({"icon": "Folder", "confidence": 0.3})

        figma_llm_ctx.set_figma_llm_context(nav_icon_query_fn=_fake_q)
        assert nav_icon_map.icon_for_with_llm("Widgets") == "folder"

    def test_llm_raises_falls_back_to_folder(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")

        def _boom(_s, _u):
            raise RuntimeError("boom")

        figma_llm_ctx.set_figma_llm_context(nav_icon_query_fn=_boom)
        assert nav_icon_map.icon_for_with_llm("Widgets") == "folder"


class TestPascalToKebab:
    def test_single_word_stays_lower(self):
        assert nav_icon_map._lucide_to_kebab("Home") == "home"
        assert nav_icon_map._lucide_to_kebab("Folder") == "folder"

    def test_multi_word_becomes_kebab(self):
        assert nav_icon_map._lucide_to_kebab("BarChart") == "bar-chart"
        assert nav_icon_map._lucide_to_kebab("ShoppingCart") == "shopping-cart"
        assert nav_icon_map._lucide_to_kebab("LayoutDashboard") == "layout-dashboard"

    def test_three_word_kebab(self):
        assert nav_icon_map._lucide_to_kebab("ClipboardList") == "clipboard-list"

    def test_already_lower_preserved(self):
        assert nav_icon_map._lucide_to_kebab("folder") == "folder"


class TestEmptyOrBlankInputs:
    def test_empty_label_returns_folder(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")
        figma_llm_ctx.set_figma_llm_context(
            nav_icon_query_fn=lambda *_: json.dumps(
                {"icon": "Sparkles", "confidence": 0.9},
            ),
        )
        # Empty label should short-circuit — never call LLM.
        assert nav_icon_map.icon_for_with_llm("") == "folder"
        assert nav_icon_map.icon_for_with_llm(None) == "folder"
        assert nav_icon_map.icon_for_with_llm("   ") == "folder"
