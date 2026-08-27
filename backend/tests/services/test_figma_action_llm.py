"""Tests for services.figma_action_llm — LLM-based Figma CTA classifier.

Every test injects a fake ``query_fn`` that returns a canned JSON
string. No live LLM calls. The module never raises — every failure
path degrades to ``FigmaActionBinding(kind="none", confidence=0.0)``.
"""

from __future__ import annotations

import pytest

from services.figma_action_llm import (
    FigmaActionBinding,
    classify_figma_action_llm,
)


def _stub(payload: str):
    """Build a ``query_fn`` that returns ``payload`` verbatim."""
    def _q(system_prompt: str, user_prompt: str) -> str:
        return payload
    return _q


# --------------------------------------------------------------------------- #
# Happy paths                                                                 #
# --------------------------------------------------------------------------- #

class TestHappyPath:
    def test_navigate_target_in_registry(self):
        r = classify_figma_action_llm(
            "Back to dashboard",
            available_routes=["/dashboard", "/candidates"],
            available_workflows=[],
            query_fn=_stub(
                '{"kind":"navigate","target":"/dashboard","confidence":0.92}'
            ),
        )
        assert r.kind == "navigate"
        assert r.target == "/dashboard"
        assert r.confidence == pytest.approx(0.92)

    def test_workflow_target_in_registry(self):
        r = classify_figma_action_llm(
            "Kick off the flow",
            available_routes=[],
            available_workflows=["submit_application", "save_draft"],
            query_fn=_stub(
                '{"kind":"workflow","target":"submit_application",'
                '"confidence":0.85}'
            ),
        )
        assert r.kind == "workflow"
        assert r.target == "submit_application"
        assert r.confidence == pytest.approx(0.85)

    def test_external_url_accepted(self):
        r = classify_figma_action_llm(
            "Docs",
            available_routes=[],
            available_workflows=[],
            query_fn=_stub(
                '{"kind":"external","target":"https://example.com/docs",'
                '"confidence":0.75}'
            ),
        )
        assert r.kind == "external"
        assert r.target == "https://example.com/docs"

    def test_explicit_none_result(self):
        r = classify_figma_action_llm(
            "???",
            available_routes=["/x"],
            available_workflows=["w1"],
            query_fn=_stub('{"kind":"none","target":null,"confidence":0.0}'),
        )
        assert r.kind == "none"
        assert r.target is None
        assert r.confidence == 0.0


# --------------------------------------------------------------------------- #
# Registry safety                                                             #
# --------------------------------------------------------------------------- #

class TestRegistrySafety:
    def test_navigate_target_outside_registry_downgrades(self):
        # LLM hallucinated a route — must degrade to none.
        r = classify_figma_action_llm(
            "Go somewhere",
            available_routes=["/dashboard"],
            available_workflows=[],
            query_fn=_stub(
                '{"kind":"navigate","target":"/imagined-route",'
                '"confidence":0.9}'
            ),
        )
        assert r.kind == "none"
        assert r.target is None
        assert r.confidence == 0.0

    def test_workflow_target_outside_registry_downgrades(self):
        r = classify_figma_action_llm(
            "Save",
            available_routes=[],
            available_workflows=["submit_application"],
            query_fn=_stub(
                '{"kind":"workflow","target":"phantom_workflow",'
                '"confidence":0.9}'
            ),
        )
        assert r.kind == "none"
        assert r.target is None

    def test_external_without_url_scheme_downgrades(self):
        r = classify_figma_action_llm(
            "Link",
            query_fn=_stub(
                '{"kind":"external","target":"not-a-url","confidence":0.6}'
            ),
        )
        assert r.kind == "none"
        assert r.target is None

    def test_empty_registries_do_not_crash(self):
        # Empty lists on both sides + a "none" response should just work.
        r = classify_figma_action_llm(
            "Anything",
            available_routes=[],
            available_workflows=[],
            query_fn=_stub('{"kind":"none","target":null,"confidence":0.0}'),
        )
        assert r.kind == "none"

    def test_navigate_with_empty_routes_downgrades(self):
        # Model chose navigate but the registry is empty — must degrade.
        r = classify_figma_action_llm(
            "Home",
            available_routes=[],
            available_workflows=["w1"],
            query_fn=_stub(
                '{"kind":"navigate","target":"/home","confidence":0.95}'
            ),
        )
        assert r.kind == "none"

    def test_none_argument_registries_work_like_empty(self):
        # Passing None for both should not raise; behaves like [].
        r = classify_figma_action_llm(
            "X",
            available_routes=None,
            available_workflows=None,
            query_fn=_stub('{"kind":"none","target":null,"confidence":0.0}'),
        )
        assert r.kind == "none"


# --------------------------------------------------------------------------- #
# Malformed / edge inputs                                                     #
# --------------------------------------------------------------------------- #

class TestMalformed:
    def test_garbage_string_falls_back_to_none(self):
        r = classify_figma_action_llm(
            "Save",
            available_routes=[],
            available_workflows=["submit"],
            query_fn=_stub("not json at all"),
        )
        assert r.kind == "none"
        assert r.confidence == 0.0

    def test_empty_string_falls_back_to_none(self):
        r = classify_figma_action_llm(
            "Save",
            available_workflows=["submit"],
            query_fn=_stub(""),
        )
        assert r.kind == "none"

    def test_unknown_kind_falls_back_to_none(self):
        # pydantic Literal should reject "teleport" → ValidationError → none.
        r = classify_figma_action_llm(
            "Zap",
            query_fn=_stub(
                '{"kind":"teleport","target":"/x","confidence":0.9}'
            ),
        )
        assert r.kind == "none"

    def test_code_fence_wrapper_is_stripped(self):
        payload = (
            "```json\n"
            '{"kind":"workflow","target":"submit","confidence":0.7}\n'
            "```"
        )
        r = classify_figma_action_llm(
            "Save",
            available_workflows=["submit"],
            query_fn=_stub(payload),
        )
        assert r.kind == "workflow"
        assert r.target == "submit"

    def test_leading_prose_before_json_is_tolerated(self):
        payload = (
            "Here you go: "
            '{"kind":"workflow","target":"submit","confidence":0.7}'
        )
        r = classify_figma_action_llm(
            "Save",
            available_workflows=["submit"],
            query_fn=_stub(payload),
        )
        assert r.kind == "workflow"
        assert r.target == "submit"

    def test_confidence_clamped_high(self):
        r = classify_figma_action_llm(
            "Save",
            available_workflows=["submit"],
            query_fn=_stub(
                '{"kind":"workflow","target":"submit","confidence":9.9}'
            ),
        )
        assert r.confidence == 1.0

    def test_confidence_clamped_low(self):
        r = classify_figma_action_llm(
            "Save",
            available_workflows=["submit"],
            query_fn=_stub(
                '{"kind":"workflow","target":"submit","confidence":-3.0}'
            ),
        )
        assert r.confidence == 0.0

    def test_query_fn_raises_falls_back(self):
        def _boom(system_prompt: str, user_prompt: str) -> str:
            raise RuntimeError("boundary blew up")

        r = classify_figma_action_llm("Save", query_fn=_boom)
        assert r.kind == "none"
        assert r.confidence == 0.0


# --------------------------------------------------------------------------- #
# Case + whitespace tolerance                                                 #
# --------------------------------------------------------------------------- #

class TestTolerance:
    def test_route_match_is_exact_not_case_insensitive(self):
        # Registry match is intentionally strict (routes are case-sensitive
        # paths). "/Dashboard" is not "/dashboard".
        r = classify_figma_action_llm(
            "Home",
            available_routes=["/dashboard"],
            query_fn=_stub(
                '{"kind":"navigate","target":"/Dashboard","confidence":0.9}'
            ),
        )
        assert r.kind == "none"

    def test_whitespace_around_payload_is_stripped(self):
        payload = (
            "   \n"
            '{"kind":"navigate","target":"/dashboard","confidence":0.8}'
            "   \n"
        )
        r = classify_figma_action_llm(
            "Home",
            available_routes=["/dashboard"],
            query_fn=_stub(payload),
        )
        assert r.kind == "navigate"
        assert r.target == "/dashboard"

    def test_surrounding_text_optional_and_ignored_in_result(self):
        # The surrounding_text is only prompt-fodder; the stub ignores it.
        r = classify_figma_action_llm(
            "Save",
            surrounding_text="parent frame: Application form",
            available_workflows=["submit"],
            query_fn=_stub(
                '{"kind":"workflow","target":"submit","confidence":0.9}'
            ),
        )
        assert r.kind == "workflow"
