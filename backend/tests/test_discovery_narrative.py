"""discovery_narrative — the pre-planner LLM turn that expands a sparse
prompt into a rich domain doc. Tests exercise:

  * ``build_narrative_prompt`` — pure — must faithfully carry every
    part of the brief into the prompt so the model can see it
  * ``expand_prompt_to_narrative`` — LLM boundary — must call the
    injected client, must swallow errors silently, must respect the
    empty-prompt fast-path
  * ``persist_narrative`` / ``read_narrative`` — disk contract
  * ``render_narrative_block`` — planner-brief injection shape
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services.discovery_narrative import (
    build_narrative_prompt,
    expand_prompt_to_narrative,
    is_narrative_enabled,
    persist_narrative,
    read_narrative,
    render_narrative_block,
)


# ────────────────────────────────────────────────────────────
# build_narrative_prompt (pure)
# ────────────────────────────────────────────────────────────

def test_build_narrative_prompt_carries_user_prompt_verbatim():
    prompt = "Design the ATS for the Cabin Crew Recruitment"
    text = build_narrative_prompt(prompt, None)
    assert prompt in text
    assert "USER PROMPT" in text


def test_build_narrative_prompt_embeds_structured_brief_as_json():
    brief = {"actors": [{"name": "Candidate"}, {"name": "Recruiter"}]}
    text = build_narrative_prompt("build ATS", brief)
    # brief content must be embedded so the model sees it
    assert "Candidate" in text
    assert "Recruiter" in text
    assert "STRUCTURED BRIEF" in text
    # embedded as JSON (predictable, model-parseable)
    assert '"actors"' in text


def test_build_narrative_prompt_no_brief_leaves_out_brief_section():
    text = build_narrative_prompt("hi", None)
    assert "STRUCTURED BRIEF" not in text


def test_build_narrative_prompt_empty_user_prompt_still_returns_string():
    text = build_narrative_prompt("", None)
    assert isinstance(text, str)
    # graceful: doesn't crash, still asks for a narrative
    assert "DOMAIN NARRATIVE" in text


# ────────────────────────────────────────────────────────────
# expand_prompt_to_narrative (LLM boundary)
# ────────────────────────────────────────────────────────────

class _FakeText:
    def __init__(self, text: str):
        self.text = text


class _FakeMessage:
    def __init__(self, text: str):
        self.content = [_FakeText(text)]


class _FakeMessages:
    def __init__(self, response_text: str = "# Narrative\n\nContent."):
        self.response_text = response_text
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeMessage(self.response_text)


class _FakeClient:
    def __init__(self, response_text: str = "# Narrative\n\nContent."):
        self.messages = _FakeMessages(response_text)


def test_expand_prompt_empty_prompt_short_circuits_no_llm_call():
    client = _FakeClient()
    result = asyncio.run(expand_prompt_to_narrative("", None, _client=client))
    assert result == ""
    assert client.messages.calls == []


def test_expand_prompt_calls_injected_client_and_returns_text():
    client = _FakeClient(response_text="# Cabin Crew ATS\n\nCandidate...")
    result = asyncio.run(expand_prompt_to_narrative(
        "Build an ATS", None, _client=client,
    ))
    assert "Cabin Crew ATS" in result
    assert len(client.messages.calls) == 1


def test_expand_prompt_passes_system_prompt_and_brief_to_llm():
    client = _FakeClient(response_text="# out")
    brief = {"actors": [{"name": "Candidate"}]}
    asyncio.run(expand_prompt_to_narrative(
        "Build ATS", brief, _client=client,
    ))
    call = client.messages.calls[0]
    # system prompt must be present and non-trivial
    assert "system" in call
    assert "DOMAIN NARRATIVE" in call["system"]
    # brief embedded in the user message
    user_msg = call["messages"][0]["content"]
    assert "Candidate" in user_msg


def test_expand_prompt_llm_exception_returns_empty_never_raises():
    class _RaisingClient:
        class messages:  # noqa: N801
            @staticmethod
            async def create(**_):
                raise RuntimeError("boom")

    result = asyncio.run(expand_prompt_to_narrative(
        "hi", None, _client=_RaisingClient(),
    ))
    assert result == ""


def test_expand_prompt_strips_whitespace_from_response():
    client = _FakeClient(response_text="\n\n  # Narrative  \n\n")
    result = asyncio.run(expand_prompt_to_narrative(
        "hi", None, _client=client,
    ))
    assert result == "# Narrative"


# ────────────────────────────────────────────────────────────
# persist_narrative / read_narrative
# ────────────────────────────────────────────────────────────

def test_persist_narrative_writes_to_contracts_folder(tmp_path):
    path = persist_narrative(tmp_path, "# Hello\n\nWorld")
    assert path is not None
    assert path == tmp_path / "contracts" / "domain-narrative.md"
    assert path.read_text(encoding="utf-8") == "# Hello\n\nWorld"


def test_persist_narrative_empty_string_writes_nothing(tmp_path):
    path = persist_narrative(tmp_path, "")
    assert path is None
    assert not (tmp_path / "contracts").exists() \
        or not any((tmp_path / "contracts").iterdir())


def test_persist_narrative_whitespace_only_writes_nothing(tmp_path):
    assert persist_narrative(tmp_path, "\n  \n") is None


def test_read_narrative_returns_persisted_content(tmp_path):
    persist_narrative(tmp_path, "# Persisted")
    assert read_narrative(tmp_path) == "# Persisted"


def test_read_narrative_returns_empty_when_missing(tmp_path):
    assert read_narrative(tmp_path) == ""


def test_persist_creates_contracts_dir_if_absent(tmp_path):
    # contracts folder doesn't exist yet
    assert not (tmp_path / "contracts").exists()
    persist_narrative(tmp_path, "# X")
    assert (tmp_path / "contracts" / "domain-narrative.md").exists()


# ────────────────────────────────────────────────────────────
# render_narrative_block
# ────────────────────────────────────────────────────────────

def test_render_narrative_block_wraps_with_header():
    block = render_narrative_block("# Cabin Crew\n\n...")
    assert block.startswith("# DOMAIN NARRATIVE")
    assert "# Cabin Crew" in block
    # header must clarify this is guidance, not a hard contract
    assert "GUIDANCE" in block


def test_render_narrative_block_empty_returns_empty_string():
    """Byte-unchanged planner input when narrative expansion is off."""
    assert render_narrative_block("") == ""
    assert render_narrative_block("   \n\n") == ""
    assert render_narrative_block(None) == ""


def test_render_narrative_block_signals_it_is_not_authoritative():
    """The planner has an existing AUTHORITATIVE INPUTS contract; the
    narrative must clearly not compete with it."""
    block = render_narrative_block("# X")
    assert "NOT" in block or "not an authoritative" in block.lower()


# ────────────────────────────────────────────────────────────
# Env gate
# ────────────────────────────────────────────────────────────

def test_is_narrative_enabled_off_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_NARRATIVE_EXPANSION", raising=False)
    assert is_narrative_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_is_narrative_enabled_accepts_truthy_values(monkeypatch, val):
    monkeypatch.setenv("FORGE_NARRATIVE_EXPANSION", val)
    assert is_narrative_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
def test_is_narrative_enabled_rejects_falsy_values(monkeypatch, val):
    monkeypatch.setenv("FORGE_NARRATIVE_EXPANSION", val)
    assert is_narrative_enabled() is False
