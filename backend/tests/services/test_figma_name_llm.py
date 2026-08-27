"""Tests for services.figma_name_llm — LLM-based Figma layer-name → component.

Every test injects a fake ``query_fn`` that returns a canned JSON
string. No live LLM calls. The module never raises — every failure
path degrades to ``FigmaNameClassification(component="Box", confidence=0.0)``.
"""

from __future__ import annotations

import pytest

from services.figma_name_llm import (
    FigmaNameClassification,
    classify_figma_name_llm,
)


def _stub(payload: str):
    def _q(system_prompt: str, user_prompt: str) -> str:
        return payload
    return _q


# --------------------------------------------------------------------------- #
# Happy paths                                                                 #
# --------------------------------------------------------------------------- #

class TestHappyPath:
    def test_component_in_registry(self):
        r = classify_figma_name_llm(
            "Onboarding step 2",
            node_type="FRAME",
            component_registry=["Card", "Section", "StatCard"],
            query_fn=_stub('{"component":"Card","confidence":0.88}'),
        )
        assert r.component == "Card"
        assert r.confidence == pytest.approx(0.88)

    def test_specific_component_preferred(self):
        # If the LLM picks a more specific component and it's in the
        # registry, we accept it verbatim (the prompt encourages this).
        r = classify_figma_name_llm(
            "Revenue tile",
            node_type="FRAME",
            component_registry=["Card", "StatCard"],
            query_fn=_stub('{"component":"StatCard","confidence":0.94}'),
        )
        assert r.component == "StatCard"

    def test_neighbors_argument_accepted(self):
        r = classify_figma_name_llm(
            "Row",
            node_type="FRAME",
            neighbors=["Header", "Footer"],
            component_registry=["Row", "Container"],
            query_fn=_stub('{"component":"Row","confidence":0.7}'),
        )
        assert r.component == "Row"


# --------------------------------------------------------------------------- #
# Registry safety                                                             #
# --------------------------------------------------------------------------- #

class TestRegistrySafety:
    def test_component_outside_registry_falls_back_to_box(self):
        r = classify_figma_name_llm(
            "Weird custom widget",
            node_type="FRAME",
            component_registry=["Card", "Section"],
            query_fn=_stub(
                '{"component":"HallucinatedComponent","confidence":0.99}'
            ),
        )
        assert r.component == "Box"
        assert r.confidence == 0.0

    def test_empty_registry_returns_box_without_calling_llm(self):
        called = {"n": 0}

        def _tracking(system_prompt: str, user_prompt: str) -> str:
            called["n"] += 1
            return '{"component":"Card","confidence":0.9}'

        r = classify_figma_name_llm(
            "Card",
            component_registry=[],
            query_fn=_tracking,
        )
        assert r.component == "Box"
        assert r.confidence == 0.0
        assert called["n"] == 0

    def test_none_registry_treated_as_empty(self):
        r = classify_figma_name_llm(
            "Anything",
            component_registry=None,
            query_fn=_stub('{"component":"Card","confidence":0.9}'),
        )
        assert r.component == "Box"

    def test_box_accepted_even_when_not_in_registry(self):
        # Box is the acknowledged fallback marker; it's always acceptable.
        r = classify_figma_name_llm(
            "Wrapper",
            component_registry=["Card", "Section"],
            query_fn=_stub('{"component":"Box","confidence":0.4}'),
        )
        assert r.component == "Box"
        assert r.confidence == pytest.approx(0.4)


# --------------------------------------------------------------------------- #
# Malformed / edge inputs                                                     #
# --------------------------------------------------------------------------- #

class TestMalformed:
    def test_garbage_string_falls_back_to_box(self):
        r = classify_figma_name_llm(
            "Card",
            component_registry=["Card"],
            query_fn=_stub("not json"),
        )
        assert r.component == "Box"
        assert r.confidence == 0.0

    def test_empty_string_falls_back_to_box(self):
        r = classify_figma_name_llm(
            "Card",
            component_registry=["Card"],
            query_fn=_stub(""),
        )
        assert r.component == "Box"

    def test_code_fence_wrapper_is_stripped(self):
        payload = (
            "```json\n"
            '{"component":"Card","confidence":0.8}\n'
            "```"
        )
        r = classify_figma_name_llm(
            "Card",
            component_registry=["Card"],
            query_fn=_stub(payload),
        )
        assert r.component == "Card"
        assert r.confidence == pytest.approx(0.8)

    def test_missing_confidence_defaults_to_zero(self):
        r = classify_figma_name_llm(
            "Card",
            component_registry=["Card"],
            query_fn=_stub('{"component":"Card"}'),
        )
        assert r.component == "Card"
        assert r.confidence == 0.0

    def test_confidence_clamped_high(self):
        r = classify_figma_name_llm(
            "Card",
            component_registry=["Card"],
            query_fn=_stub('{"component":"Card","confidence":5.0}'),
        )
        assert r.confidence == 1.0

    def test_query_fn_raises_falls_back(self):
        def _boom(system_prompt: str, user_prompt: str) -> str:
            raise RuntimeError("boom")

        r = classify_figma_name_llm(
            "Card",
            component_registry=["Card"],
            query_fn=_boom,
        )
        assert r.component == "Box"

    def test_leading_prose_before_json_is_tolerated(self):
        payload = 'Sure: {"component":"Card","confidence":0.7}'
        r = classify_figma_name_llm(
            "Card",
            component_registry=["Card"],
            query_fn=_stub(payload),
        )
        assert r.component == "Card"


# --------------------------------------------------------------------------- #
# Tolerance                                                                   #
# --------------------------------------------------------------------------- #

class TestTolerance:
    def test_case_sensitive_registry_match(self):
        # Registry membership is strict (PascalCase component names).
        # "card" is not "Card".
        r = classify_figma_name_llm(
            "Card",
            component_registry=["Card"],
            query_fn=_stub('{"component":"card","confidence":0.9}'),
        )
        assert r.component == "Box"

    def test_whitespace_around_payload_is_stripped(self):
        payload = '   {"component":"Card","confidence":0.7}   '
        r = classify_figma_name_llm(
            "Card",
            component_registry=["Card"],
            query_fn=_stub(payload),
        )
        assert r.component == "Card"

    def test_node_type_default_empty_ok(self):
        # node_type default (empty string) must not break the call.
        r = classify_figma_name_llm(
            "Card",
            component_registry=["Card"],
            query_fn=_stub('{"component":"Card","confidence":0.7}'),
        )
        assert r.component == "Card"
