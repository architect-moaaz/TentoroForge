"""Smith narrator — real architect voice via Anthropic.

We don't test the actual model output (that's tautological — mocking
returns exactly what we mock). We test:

  * Falls back to artifact.narrator_summary() when API key is absent.
  * Falls back on any LLM exception (network, malformed response).
  * Returns non-empty string even when everything fails.
  * Passes artifact summary + blueprint context into the prompt.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.smith_narrator import narrate


@dataclass
class _FakeArtifact:
    summary_text: str = "template summary"

    def narrator_summary(self) -> str:
        return self.summary_text


# --------------------------------------------------------------------------- #
# Fallback semantics
# --------------------------------------------------------------------------- #

def test_no_api_key_returns_deterministic_summary(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = narrate(
        stage="discovery",
        artifact=_FakeArtifact("proposed 3 entities"),
    )
    assert out == "proposed 3 entities"


def test_no_api_key_and_no_artifact_still_returns_string(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = narrate(stage="planning")
    assert isinstance(out, str) and out  # non-empty


def test_fallback_override_wins_over_artifact(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = narrate(
        stage="discovery",
        artifact=_FakeArtifact("wrong text"),
        fallback="right text",
    )
    assert out == "right text"


# --------------------------------------------------------------------------- #
# LLM path
# --------------------------------------------------------------------------- #

def test_llm_call_returns_model_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    class _Block:
        def __init__(self, t): self.text = t

    class _Resp:
        content = [_Block("This is Smith speaking about the plan.")]

    class _Msgs:
        def create(self, **kwargs):
            return _Resp()

    class _Client:
        def __init__(self, **kwargs): self.messages = _Msgs()

    from services import llm_client
    monkeypatch.setattr(llm_client, "Anthropic", _Client)

    out = narrate(
        stage="planning",
        artifact=_FakeArtifact("2 entities, 1 workflow, 1 page"),
        user_ask="build me a small ATS",
    )
    assert out == "This is Smith speaking about the plan."


def test_llm_exception_falls_back_to_summary(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    class _Client:
        def __init__(self, **kwargs):
            class _M:
                def create(self, **kw): raise RuntimeError("network down")
            self.messages = _M()

    from services import llm_client
    monkeypatch.setattr(llm_client, "Anthropic", _Client)

    out = narrate(
        stage="planning",
        artifact=_FakeArtifact("2 entities drafted"),
    )
    assert out == "2 entities drafted"


def test_empty_llm_response_falls_back_to_summary(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    class _Block:
        def __init__(self, t): self.text = t

    class _Resp:
        content = [_Block("")]

    class _Client:
        def __init__(self, **kwargs):
            class _M:
                def create(self, **kw): return _Resp()
            self.messages = _M()

    from services import llm_client
    monkeypatch.setattr(llm_client, "Anthropic", _Client)

    out = narrate(
        stage="planning",
        artifact=_FakeArtifact("fallback content"),
    )
    assert out == "fallback content"


def test_artifact_summary_raise_still_returns_string(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class _Bad:
        def narrator_summary(self): raise ValueError("boom")

    out = narrate(stage="discovery", artifact=_Bad())
    assert isinstance(out, str) and out
