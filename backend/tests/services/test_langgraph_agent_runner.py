"""LangGraph transport (Phase 1) — parity with sdk_agent_runner's contract."""
from __future__ import annotations

import json

import pytest
from services.agent_messages import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from services.langgraph_agent_runner import (
    _accumulate_usage,
    _ai_to_blocks,
    _build_tools,
    query,
)


class _FakeToolModel(FakeMessagesListChatModel):
    """Scripted chat model that accepts bind_tools (returns itself)."""

    def bind_tools(self, tools, **kwargs):  # noqa: D102
        return self


class _Opts:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ── translation helpers ──────────────────────────────────────────────────

def test_ai_to_blocks_string_content():
    blocks = _ai_to_blocks(AIMessage(content="hello"))
    assert len(blocks) == 1 and isinstance(blocks[0], TextBlock)
    assert blocks[0].text == "hello"


def test_ai_to_blocks_tool_calls_and_list_content():
    msg = AIMessage(
        content=[{"type": "text", "text": "writing now"}],
        tool_calls=[{"id": "t1", "name": "Write",
                     "args": {"file_path": "a.txt", "content": "x"}}],
    )
    blocks = _ai_to_blocks(msg)
    assert isinstance(blocks[0], TextBlock) and blocks[0].text == "writing now"
    tu = blocks[1]
    assert isinstance(tu, ToolUseBlock)
    assert tu.name == "Write" and tu.input["file_path"] == "a.txt"


def test_accumulate_usage_sums_cache_details():
    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    msg = AIMessage(content="x")
    msg.usage_metadata = {
        "input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
        "input_token_details": {"cache_read": 60, "cache_creation": 10},
    }
    _accumulate_usage(totals, msg)
    _accumulate_usage(totals, msg)
    assert totals == {"input_tokens": 200, "output_tokens": 40,
                      "cache_read_input_tokens": 120,
                      "cache_creation_input_tokens": 20}


# ── tools execute against the real filesystem ────────────────────────────

def test_build_tools_write_read_edit_glob(tmp_path):
    tools = {t.name: t for t in _build_tools(str(tmp_path), {"Write", "Read", "Glob", "Edit"})}
    assert set(tools) == {"Write", "Read", "Glob", "Edit"}
    assert "Wrote" in tools["Write"].invoke({"file_path": "src/a.txt", "content": "one"})
    assert tools["Read"].invoke({"file_path": "src/a.txt"}) == "one"
    assert "src/a.txt" in tools["Glob"].invoke({"pattern": "src/*.txt"})
    tools["Edit"].invoke({"file_path": "src/a.txt", "old_string": "one", "new_string": "two"})
    assert (tmp_path / "src" / "a.txt").read_text() == "two"


def test_build_tools_respects_allowlist(tmp_path):
    names = {t.name for t in _build_tools(str(tmp_path), {"Read", "Glob"})}
    assert names == {"Read", "Glob"}


# ── end-to-end loop on a scripted model ──────────────────────────────────

@pytest.mark.asyncio
async def test_query_runs_tool_loop_and_writes_file(tmp_path, monkeypatch):
    """Model asks for a Write, then finishes: the file lands on disk and the
    stream is AssistantMessage(tool use) → AssistantMessage(text) →
    ResultMessage(success) — the exact shape sse_helpers consumes."""
    scripted = _FakeToolModel(responses=[
        AIMessage(content="", tool_calls=[
            {"id": "c1", "name": "Write",
             "args": {"file_path": "out/hello.txt", "content": "hi"}}]),
        AIMessage(content="done"),
    ])
    import langchain_anthropic
    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic",
                        lambda **kw: scripted)

    msgs = []
    async for m in query(prompt="write hello", options=_Opts(
            cwd=str(tmp_path), model="claude-sonnet-4-6", max_turns=4,
            system_prompt="You are a file writer.")):
        msgs.append(m)

    assert (tmp_path / "out" / "hello.txt").read_text() == "hi"
    assistants = [m for m in msgs if isinstance(m, AssistantMessage)]
    assert any(isinstance(b, ToolUseBlock) and b.name == "Write"
               for m in assistants for b in m.content)
    assert any(isinstance(b, TextBlock) and b.text == "done"
               for m in assistants for b in m.content)
    result = msgs[-1]
    assert isinstance(result, ResultMessage)
    assert result.subtype == "success" and not result.is_error
    assert result.num_turns == 2


# ── flag dispatch through the sdk_agent_runner seam ──────────────────────

@pytest.mark.asyncio
async def test_forge_langgraph_flag_routes_through_seam(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_LANGGRAPH", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    calls = []

    async def _fake_lg_query(*, prompt, options):
        calls.append(prompt)
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=0,
                            is_error=False, num_turns=1, session_id="langgraph-runner",
                            total_cost_usd=0.0)

    import services.langgraph_agent_runner as lgr
    monkeypatch.setattr(lgr, "query", _fake_lg_query)

    from services.sdk_agent_runner import query as seam_query
    out = [m async for m in seam_query(prompt="p", options=_Opts(cwd=str(tmp_path)))]
    assert calls == ["p"]
    assert isinstance(out[-1], ResultMessage)
    assert out[-1].session_id == "langgraph-runner"
