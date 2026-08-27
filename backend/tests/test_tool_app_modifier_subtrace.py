"""Slice 3 — sub-agent trace forwarding.

When Smith calls `_tool_app_modifier`, the sub-agent's per-step trace
lives inside the returned envelope. Slice 3 preserves it on Smith's
trace step (as ``sub_trace``) so the outer SSE emitter can stream each
inner Read/Bash/Edit as its own ``smith_thought`` chip.

Two boundaries to exercise:
  1. smith_agent.run_smith_agent captures ``sub_trace`` on the trace entry.
  2. _handle_smith_turn emits sibling ``smith_thought`` events per inner step.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


# --------------------------------------------------------------------------- #
# Boundary 1: run_smith_agent preserves sub_trace
# --------------------------------------------------------------------------- #

def test_run_smith_agent_captures_sub_trace(tmp_path, monkeypatch):
    """When a tool returns {trace: [...]}, run_smith_agent must attach
    a projected ``sub_trace`` to its own trace entry."""
    from agents.smith_agent import run_smith_agent
    import services.smith_tools as st

    # Stub the tool: register a fake handler that returns a trace-carrying dict.
    def _fake_modifier(output_dir, args):
        return {
            "status": "applied",
            "summary": "did stuff",
            "files_touched": [{"path": "src/schemas/foo.json", "action": "modified"}],
            "trace": [
                {"tool": "Read", "args": {"path": "registry.json"},
                 "result_summary": "42 entities"},
                {"tool": "Edit", "args": {"path": "src/schemas/foo.json"},
                 "result_summary": "replaced 1 match"},
            ],
        }
    monkeypatch.setitem(st.READONLY_HANDLERS, "_tool_app_modifier", _fake_modifier)

    # Stub the LLM boundary: understand_ask (mandatory before any mutation),
    # then the _tool_app_modifier call, then answer.
    def _fake_query(system_prompt, messages, catalog):
        yield {"tool": "understand_ask", "args": {
            "screen": "Add Candidate",
            "element_label": "Upload CV",
            "current_behavior": "Select dropdown",
            "desired_behavior": "FileUpload",
            "target_file": "src/schemas/foo.json",
        }}
        yield {"tool": "_tool_app_modifier",
               "args": {"ask": "swap CV to FileUpload"}}
        yield {"tool": "answer", "args": {"text": "Done."}}

    result = run_smith_agent(
        user_message="swap CV to FileUpload",
        output_dir=str(tmp_path),
        recall_block="", memory_block="",
        query_fn=_fake_query,
    )

    trace = result["trace"]
    # Find the modifier's outer entry
    mod_entry = next(
        s for s in trace if s.get("tool") == "_tool_app_modifier"
    )
    assert isinstance(mod_entry.get("sub_trace"), list)
    inner_tools = [s["tool"] for s in mod_entry["sub_trace"]]
    assert inner_tools == ["Read", "Edit"]
    # edited_paths harvested from files_touched
    assert "src/schemas/foo.json" in result["edited_paths"]


def test_run_smith_agent_no_sub_trace_when_tool_has_none(tmp_path, monkeypatch):
    """Regular tools (no ``trace`` field in result) don't produce sub_trace."""
    from agents.smith_agent import run_smith_agent
    import services.smith_tools as st

    def _fake_recall(output_dir, args):
        return {"promptBlock": "APP INTENT: X"}
    monkeypatch.setitem(st.READONLY_HANDLERS, "recall", _fake_recall)

    def _fake_query(system_prompt, messages, catalog):
        yield {"tool": "recall", "args": {}}
        yield {"tool": "answer", "args": {"text": "X"}}

    result = run_smith_agent(
        user_message="hi", output_dir=str(tmp_path),
        recall_block="", memory_block="",
        query_fn=_fake_query,
    )
    recall_entry = next(s for s in result["trace"] if s.get("tool") == "recall")
    assert "sub_trace" not in recall_entry


# --------------------------------------------------------------------------- #
# Boundary 2: _handle_smith_turn expands sub_trace to sibling SSE events
# --------------------------------------------------------------------------- #

def _collect(gen):
    events = []
    try:
        import asyncio as _a
        loop = _a.new_event_loop()
        async def _run():
            async for e in gen:
                events.append(e)
        loop.run_until_complete(_run())
        loop.close()
    except Exception:  # noqa: BLE001
        pass
    return events


def _stub_smith_router(monkeypatch, agent_result):
    """Wire generate._handle_smith_turn against fakes. Same shape as
    the existing test_smith_router.py::_stub_router."""
    import routers.generate as g
    import services.app_recall as ar
    import services.smith_memory as sm
    import agents.smith_agent as sa

    async def _no_pending(_pid):
        return None
    async def _persist(project_id, content, message_type, metadata=None):
        pass
    def _empty_recall(_output_dir):
        return SimpleNamespace(to_prompt_block=lambda: "APP INTENT: test")
    async def _empty_memory(*_a, **_kw):
        return SimpleNamespace(to_prompt_block=lambda: "<smith-memory>none</smith-memory>")
    def _fake_agent(user_message, output_dir, recall_block, memory_block, **_kw):
        return agent_result

    monkeypatch.setattr(g, "_load_pending_fix", _no_pending)
    monkeypatch.setattr(g, "_persist_assistant_message", _persist)
    monkeypatch.setattr(ar, "assemble_recall", _empty_recall)
    monkeypatch.setattr(sm, "read_smith_memory", _empty_memory)
    monkeypatch.setattr(sa, "run_smith_agent", _fake_agent)
    return g


def test_handle_smith_turn_expands_sub_trace(monkeypatch):
    """_handle_smith_turn must emit sibling smith_thought events for
    each inner step of a sub-agent tool call, prefixed with `↳ `."""
    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "0")
    result = {
        "answer": "Swapped CV Select to FileUpload.",
        "question": None, "handoff": None, "diagnosis": None,
        "edited_paths": ["src/schemas/candidates/apply.json"],
        "trace": [
            {"tool": "_tool_app_modifier",
             "args": {"ask": "swap CV to FileUpload"},
             "result_summary": "applied 1 file",
             "sub_trace": [
                 {"tool": "Read", "summary": "Read registry.json — 6 entities"},
                 {"tool": "Bash", "summary": "grep 'CV Upload' → 1 hit"},
                 {"tool": "Edit", "summary": "Edit apply.json — 1 match replaced"},
             ]},
            {"tool": "answer", "args": {"text": "…"}, "result_summary": "answer"},
        ],
    }
    g = _stub_smith_router(monkeypatch, result)
    project = SimpleNamespace(id="p1", output_dir="/tmp/app")
    events = _collect(g._handle_smith_turn(project, "swap CV to FileUpload"))

    thoughts = [
        json.loads(e["data"]) for e in events if e["event"] == "smith_thought"
    ]
    # Outer wrapper + 3 inner (Read, Bash, Edit). Answer terminal is not a thought.
    tools = [t["tool"] for t in thoughts]
    assert "_tool_app_modifier" in tools
    assert "↳ Read" in tools
    assert "↳ Bash" in tools
    assert "↳ Edit" in tools


def test_handle_smith_turn_no_sub_trace_no_extra_chips(monkeypatch):
    """Ordinary trace steps (no sub_trace) do NOT emit extra chips."""
    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "0")
    result = {
        "answer": "Done", "question": None, "handoff": None, "diagnosis": None,
        "edited_paths": [],
        "trace": [
            {"tool": "recall", "args": {}, "result_summary": "APP INTENT"},
            {"tool": "answer", "args": {"text": "Done"}, "result_summary": "answer"},
        ],
    }
    g = _stub_smith_router(monkeypatch, result)
    project = SimpleNamespace(id="p1", output_dir="/tmp/app")
    events = _collect(g._handle_smith_turn(project, "hi"))

    thoughts = [
        json.loads(e["data"]) for e in events if e["event"] == "smith_thought"
    ]
    # Exactly one thought (recall). No ↳ prefixed chips.
    assert len(thoughts) == 1
    assert thoughts[0]["tool"] == "recall"
    assert not any(t["tool"].startswith("↳") for t in thoughts)
