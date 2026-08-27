"""Tests for services.figma_llm_ctx.context_from_plan (Spec D Wave 5-C).

Verifies the plan → closed-vocabulary derivation the top-level Figma
entrypoint uses to populate the LLM classifier context before running
the walk.
"""
from __future__ import annotations

import pytest

from services import figma_llm_ctx


@pytest.fixture(autouse=True)
def _clean_ctx():
    figma_llm_ctx.reset_figma_llm_context()
    yield
    figma_llm_ctx.reset_figma_llm_context()


class TestRouteExtraction:
    def test_extracts_page_routes(self):
        plan = {"pages": [
            {"route": "/candidates"},
            {"route": "/roles"},
            {"route": "/dashboard"},
        ]}
        ctx = figma_llm_ctx.context_from_plan(plan)
        assert set(ctx["routes"]) == {"/candidates", "/roles", "/dashboard"}

    def test_dedupes_routes(self):
        plan = {"pages": [
            {"route": "/x"},
            {"route": "/x"},
            {"route": "/y"},
        ]}
        ctx = figma_llm_ctx.context_from_plan(plan)
        assert ctx["routes"] == ["/x", "/y"]

    def test_sorted_output(self):
        plan = {"pages": [
            {"route": "/zeta"},
            {"route": "/alpha"},
            {"route": "/mu"},
        ]}
        ctx = figma_llm_ctx.context_from_plan(plan)
        assert ctx["routes"] == ["/alpha", "/mu", "/zeta"]

    def test_ignores_non_string_routes(self):
        plan = {"pages": [
            {"route": None},
            {"route": ""},
            {"route": 42},
            {"route": "/keep"},
        ]}
        ctx = figma_llm_ctx.context_from_plan(plan)
        assert ctx["routes"] == ["/keep"]

    def test_ignores_routes_without_leading_slash(self):
        plan = {"pages": [
            {"route": "candidates"},
            {"route": "//weird"},   # kept — starts with /
            {"route": "/normal"},
        ]}
        ctx = figma_llm_ctx.context_from_plan(plan)
        assert "/normal" in ctx["routes"]
        assert "candidates" not in ctx["routes"]

    def test_missing_pages_key(self):
        assert figma_llm_ctx.context_from_plan({})["routes"] == []

    def test_none_plan(self):
        assert figma_llm_ctx.context_from_plan(None)["routes"] == []


class TestWorkflowExtraction:
    def test_extracts_workflow_names(self):
        plan = {"workflows": [
            {"name": "submit_application"},
            {"name": "reject_candidate"},
        ]}
        ctx = figma_llm_ctx.context_from_plan(plan)
        assert set(ctx["workflows"]) == {"submit_application", "reject_candidate"}

    def test_dedupes_and_trims(self):
        plan = {"workflows": [
            {"name": "  x  "},
            {"name": "x"},
            {"name": "y"},
        ]}
        ctx = figma_llm_ctx.context_from_plan(plan)
        assert ctx["workflows"] == ["x", "y"]

    def test_ignores_non_string_or_blank_names(self):
        plan = {"workflows": [
            {"name": None},
            {"name": ""},
            {"name": 123},
            {"name": "keep"},
        ]}
        ctx = figma_llm_ctx.context_from_plan(plan)
        assert ctx["workflows"] == ["keep"]

    def test_sorted_output(self):
        plan = {"workflows": [
            {"name": "zeta"},
            {"name": "alpha"},
        ]}
        ctx = figma_llm_ctx.context_from_plan(plan)
        assert ctx["workflows"] == ["alpha", "zeta"]


class TestComponentRegistry:
    def test_component_registry_key_always_present(self):
        # Whether or not the library registry module loads, the key is
        # always in the returned dict (empty list on failure is fine —
        # the Wave 5 wire treats empty as "LLM path ineligible").
        ctx = figma_llm_ctx.context_from_plan({})
        assert "component_registry" in ctx
        assert isinstance(ctx["component_registry"], list)


class TestNavIconSet:
    def test_nav_icons_populated_from_lucide_set(self):
        ctx = figma_llm_ctx.context_from_plan({})
        # nav_icon_llm.LUCIDE_ICON_SET is a frozenset of ~60 names,
        # always importable. Assert we got a non-empty sorted list.
        assert len(ctx["nav_icon_set"]) >= 40
        assert ctx["nav_icon_set"] == sorted(ctx["nav_icon_set"])
        # Sanity: a few canonical entries.
        assert "Home" in ctx["nav_icon_set"]
        assert "Folder" in ctx["nav_icon_set"]


class TestIntegrationWithSetter:
    def test_splatting_result_into_setter_populates_context(self):
        plan = {
            "pages":     [{"route": "/a"}, {"route": "/b"}],
            "workflows": [{"name": "wf1"}, {"name": "wf2"}],
        }
        ctx = figma_llm_ctx.context_from_plan(plan)
        figma_llm_ctx.set_figma_llm_context(**ctx)
        assert figma_llm_ctx.get_routes() == ["/a", "/b"]
        assert figma_llm_ctx.get_workflows() == ["wf1", "wf2"]

    def test_never_raises_on_malformed_plan(self):
        # Every subkey may be junk; the helper should still return a
        # dict-shape result the caller can splat safely.
        junk = {
            "pages":     "not a list",
            "workflows": 42,
        }
        ctx = figma_llm_ctx.context_from_plan(junk)  # type: ignore[arg-type]
        assert ctx["routes"] == []
        assert ctx["workflows"] == []
