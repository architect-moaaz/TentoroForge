"""Wire-in tests for Spec D Wave 5 — LLM action classifier in
services.jsx_to_schema. The keyword classifier stays as fallback; the
LLM path only fires when FORGE_FIGMA_LLM is set AND the caller has
populated the LLM context with a non-empty registry.
"""
from __future__ import annotations

import json

import pytest

from services import jsx_to_schema


@pytest.fixture(autouse=True)
def _clean_ctx(monkeypatch):
    jsx_to_schema.reset_figma_llm_context()
    monkeypatch.delenv("FORGE_FIGMA_LLM", raising=False)
    yield
    jsx_to_schema.reset_figma_llm_context()


class TestKeywordFallback:
    def test_flag_off_uses_keyword_classifier(self):
        # No flag → keyword classifier for "Sign in" emits workflow=auth.login.
        r = jsx_to_schema._classify_button_action_with_llm(
            "Sign in", data_name="", class_name="",
        )
        assert r == {"workflow": "auth.signIn"}

    def test_flag_on_but_empty_registry_uses_keyword(self, monkeypatch):
        # Flag set, but no routes/workflows populated → LLM never fires.
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")
        r = jsx_to_schema._classify_button_action_with_llm(
            "Sign in", data_name="", class_name="",
        )
        assert r == {"workflow": "auth.signIn"}


class TestLLMPathFires:
    def test_llm_workflow_binding_wins(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")
        # LLM says "workflow=submit_application", registry contains it.
        def _fake_q(_s, _u):
            return json.dumps({
                "kind": "workflow",
                "target": "submit_application",
                "confidence": 0.95,
            })
        jsx_to_schema.set_figma_llm_context(
            workflows=["submit_application"],
            routes=[],
            action_query_fn=_fake_q,
        )
        r = jsx_to_schema._classify_button_action_with_llm(
            "Kick off the flow", data_name="Submit button", class_name="",
        )
        assert r == {"workflow": "submit_application"}

    def test_llm_navigate_binding_wins(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")
        def _fake_q(_s, _u):
            return json.dumps({
                "kind": "navigate",
                "target": "/candidates",
                "confidence": 0.9,
            })
        jsx_to_schema.set_figma_llm_context(
            routes=["/candidates", "/roles"],
            workflows=[],
            action_query_fn=_fake_q,
        )
        r = jsx_to_schema._classify_button_action_with_llm(
            "View the pipeline", data_name="", class_name="",
        )
        assert r == {"navigate": "/candidates"}


class TestLLMFallsThroughToKeyword:
    def test_llm_none_falls_through_to_keyword(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")
        def _fake_q(_s, _u):
            return json.dumps({"kind": "none", "target": None, "confidence": 0.0})
        jsx_to_schema.set_figma_llm_context(
            routes=["/x"], workflows=["y"], action_query_fn=_fake_q,
        )
        # Falls through → keyword classifier picks up "Sign in".
        r = jsx_to_schema._classify_button_action_with_llm(
            "Sign in", data_name="", class_name="",
        )
        assert r == {"workflow": "auth.signIn"}

    def test_llm_off_registry_target_falls_through(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")
        def _fake_q(_s, _u):
            return json.dumps({
                "kind": "workflow", "target": "hallucinated_wf",
                "confidence": 0.9,
            })
        jsx_to_schema.set_figma_llm_context(
            routes=[], workflows=["submit_application"],  # doesn't match
            action_query_fn=_fake_q,
        )
        # Registry-safety inside classify_figma_action_llm drops to none →
        # keyword classifier still runs and emits its own answer.
        r = jsx_to_schema._classify_button_action_with_llm(
            "Sign in", data_name="", class_name="",
        )
        assert r == {"workflow": "auth.signIn"}

    def test_llm_raises_falls_through(self, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "1")
        def _boom(_s, _u):
            raise RuntimeError("LLM broke")
        jsx_to_schema.set_figma_llm_context(
            routes=["/x"], workflows=["y"], action_query_fn=_boom,
        )
        # Never crashes the transform; keyword path resolves.
        r = jsx_to_schema._classify_button_action_with_llm(
            "Sign in", data_name="", class_name="",
        )
        assert r == {"workflow": "auth.signIn"}


class TestFlagShapeTolerance:
    def test_various_truthy_flag_values(self, monkeypatch):
        for v in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("FORGE_FIGMA_LLM", v)
            assert jsx_to_schema._figma_llm_enabled() is True

    def test_various_falsey_flag_values(self, monkeypatch):
        for v in ("", "0", "false", "no", "off"):
            monkeypatch.setenv("FORGE_FIGMA_LLM", v)
            assert jsx_to_schema._figma_llm_enabled() is False


class TestContextSetter:
    def test_partial_updates_leave_other_keys_alone(self):
        jsx_to_schema.set_figma_llm_context(
            routes=["/a"], workflows=["b"], action_query_fn=lambda *_: "",
        )
        jsx_to_schema.set_figma_llm_context(routes=["/x"])  # partial
        assert jsx_to_schema._FIGMA_LLM_CTX["routes"] == ["/x"]
        assert jsx_to_schema._FIGMA_LLM_CTX["workflows"] == ["b"]
        assert jsx_to_schema._FIGMA_LLM_CTX["action_query_fn"] is not None

    def test_reset_clears_all(self):
        jsx_to_schema.set_figma_llm_context(routes=["/a"], workflows=["b"])
        jsx_to_schema.reset_figma_llm_context()
        assert jsx_to_schema._FIGMA_LLM_CTX["routes"] == []
        assert jsx_to_schema._FIGMA_LLM_CTX["workflows"] == []
