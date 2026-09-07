"""Slice 2 — Smith calls _tool_app_modifier.

Tests:
  * Catalog + handler map register the sub-agent.
  * Dispatch handler builds an ask envelope and calls the sync wrapper.
  * Empty-ask short-circuit returns a ``blocked`` envelope with a
    user-facing question.
  * Sync wrapper adapts the SDK boundary (mocked) end-to-end.
  * Smith's system prompt names the sub-agent so the LLM knows about it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import smith_tools
from agents import tool_app_modifier as tam


def _seed(tmp_path):
    (tmp_path / "src" / "schemas" / "candidates").mkdir(parents=True)
    (tmp_path / "src" / "schemas" / "candidates" / "new.json").write_text(
        '{"root": {"type": "Select"}}'
    )
    (tmp_path / "contracts").mkdir(exist_ok=True)
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {"Candidate": {}}, "pages": [], "workflows": [], "dataSources": [],
    }), encoding="utf-8")
    (tmp_path / "plan.json").write_text(json.dumps({
        "data_models": [], "pages": [], "workflows": [],
    }), encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

def test_tool_app_modifier_in_catalog():
    names = {t["name"] for t in smith_tools.TOOL_CATALOG}
    assert "_tool_app_modifier" in names


def test_tool_app_modifier_in_handler_map():
    assert "_tool_app_modifier" in smith_tools.READONLY_HANDLERS


def test_catalog_entry_documents_the_ask_arg():
    entry = next(
        t for t in smith_tools.TOOL_CATALOG if t["name"] == "_tool_app_modifier"
    )
    assert "ask" in entry["signature"]
    assert "MUTATION" in entry["desc"].upper() or "mutation" in entry["desc"]


# --------------------------------------------------------------------------- #
# Empty-ask short-circuit
# --------------------------------------------------------------------------- #

def test_empty_ask_returns_blocked_envelope(tmp_path):
    handler = smith_tools.READONLY_HANDLERS["_tool_app_modifier"]
    r = handler(str(tmp_path), {})
    assert r["status"] == "blocked"
    assert r["question_for_user"]
    assert r["files_touched"] == []


def test_whitespace_only_ask_treated_as_empty(tmp_path):
    handler = smith_tools.READONLY_HANDLERS["_tool_app_modifier"]
    r = handler(str(tmp_path), {"ask": "   \n\t  "})
    assert r["status"] == "blocked"


# --------------------------------------------------------------------------- #
# End-to-end: SDK boundary mocked, real sync wrapper, real handler
# --------------------------------------------------------------------------- #

def test_sync_wrapper_delegates_via_handler(tmp_path, monkeypatch):
    """Smith's tool dispatch path — synchronous, cannot await — must
    successfully invoke the async modifier and receive an envelope."""
    _seed(tmp_path)

    # Guard suite noop so we don't drag deterministic checks into this test.
    monkeypatch.setattr(
        "services.post_generate_fixes.apply_post_generate_fixes_with_result",
        lambda _: type("R", (), {"failures": []})(),
    )

    # Mock the SDK query: yield an Edit + answer terminal.
    def _fake_sdk_query(system_prompt, messages, catalog):
        yield {"tool": "Edit", "args": {
            "path": "src/schemas/candidates/new.json",
            "old_string": '"Select"', "new_string": '"FileUpload"',
        }}
        yield {"tool": "answer", "args": {"text": "Swapped Select → FileUpload"}}
    monkeypatch.setattr("agents.fix_chat_agent._default_query", _fake_sdk_query)

    handler = smith_tools.READONLY_HANDLERS["_tool_app_modifier"]
    r = handler(str(tmp_path), {"ask": "make it FileUpload"})

    assert r["status"] == "applied"
    assert "FileUpload" in r["summary"]
    assert any(f["path"].endswith("new.json") for f in r["files_touched"])
    # File actually changed
    assert "FileUpload" in (tmp_path / "src" / "schemas" / "candidates" / "new.json").read_text(encoding="utf-8")


def test_sync_wrapper_survives_sdk_crash(tmp_path, monkeypatch):
    """A crash inside the SDK boundary produces a ``failed`` envelope
    rather than propagating an exception into Smith's dispatch."""
    _seed(tmp_path)

    def _crashing_sdk(system_prompt, messages, catalog):
        raise RuntimeError("simulated SDK boom")
    monkeypatch.setattr("agents.fix_chat_agent._default_query", _crashing_sdk)

    handler = smith_tools.READONLY_HANDLERS["_tool_app_modifier"]
    r = handler(str(tmp_path), {"ask": "do something"})
    assert r["status"] == "failed"
    assert "boom" in r["summary"].lower() or "runtime" in r["summary"].lower()


# --------------------------------------------------------------------------- #
# Smith's system prompt names the sub-agent
# --------------------------------------------------------------------------- #

def test_smith_system_prompt_mentions_tool_app_modifier():
    from agents.smith_agent import build_system_prompt
    prompt = build_system_prompt()
    assert "_tool_app_modifier" in prompt
    # Also mentions when to call it
    assert "mutation" in prompt.lower() or "modify" in prompt.lower()


def test_smith_system_prompt_lists_tool_in_palette():
    """build_system_prompt appends the live TOOL_CATALOG. Sub-agent
    must appear as one of the callable tools."""
    from agents.smith_agent import build_system_prompt
    prompt = build_system_prompt()
    # It's the tool name from smith_tools.TOOL_CATALOG appended at the end
    assert "- _tool_app_modifier(" in prompt
