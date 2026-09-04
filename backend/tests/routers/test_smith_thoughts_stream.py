"""Smith's thinking reaches the user on the path the user is actually on.

The queue, the heartbeat, the `smith_thought` SSE event and the frontend's
collapsible reasoning renderer were all built. They lived inside the `else:`
arm of a three-way branch whose first arm — `FORGE_SMITH_ARCHITECT`, default
ON — is the one every real turn takes. So the machinery worked and nobody had
ever seen it: `reasoning_callback` was never passed, the queue was never
created, and the user watched a spinner for the whole run.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest


def _collect(agen) -> list:
    async def _run():
        return [ev async for ev in agen]
    return asyncio.run(_run())


def _thoughts(events):
    return [json.loads(e["data"]) for e in events if e["event"] == "smith_thought"]


@pytest.fixture()
def architect_turn(monkeypatch, tmp_path):
    """A Smith turn on the architect path, with the model seam faked."""
    import agents.smith_agent as sa
    import routers.generate as g
    import services.app_recall as ar
    import services.smith_memory as sm

    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "1")
    (tmp_path / "src").mkdir()

    async def _no_pending(_pid):
        return None

    async def _persist(*_a, **_kw):
        return None

    async def _empty_memory(*_a, **_kw):
        return SimpleNamespace(to_prompt_block=lambda: "")

    async def _no_prior(*_a, **_kw):
        return []

    monkeypatch.setattr(g, "_load_pending_fix", _no_pending)
    monkeypatch.setattr(g, "_persist_assistant_message", _persist)
    monkeypatch.setattr(ar, "assemble_recall", lambda _o:
                        SimpleNamespace(to_prompt_block=lambda: "APP: test"))
    monkeypatch.setattr(sm, "read_smith_memory", _empty_memory)
    monkeypatch.setattr(sm, "load_chat_history_for_prompt", _no_prior)

    captured: dict = {}

    def _fake_agent(*, user_message, output_dir, recall_block, memory_block,
                    reasoning_callback=None, progress_callback=None, **_kw):
        captured["reasoning_callback"] = reasoning_callback
        captured["progress_callback"] = progress_callback
        if reasoning_callback:
            reasoning_callback("The dashboard route has no layout.")
        if progress_callback:
            progress_callback({"phase": "tool_start", "tool": "list_pages",
                               "args": {}})
        return {"answer": "Composed the dashboard.", "trace": [],
                "edited_paths": []}

    monkeypatch.setattr(sa, "run_smith_agent", _fake_agent)
    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))
    return g, project, captured


def test_the_architect_path_receives_both_callbacks(architect_turn):
    """The agent has always accepted them; this branch never passed them."""
    g, project, captured = architect_turn
    _collect(g._handle_smith_turn(project, "build the dashboard at /"))
    assert callable(captured.get("reasoning_callback"))
    assert callable(captured.get("progress_callback"))


def test_reasoning_and_tool_chips_reach_the_stream(architect_turn):
    g, project, _ = architect_turn
    events = _collect(g._handle_smith_turn(project, "build the dashboard at /"))
    kinds = [t.get("kind") for t in _thoughts(events)]
    assert "reasoning" in kinds, "Smith's thinking never reached the user"
    assert "tool_start" in kinds, "no tool chip — the chat shows no motion"

    reasoning = next(t for t in _thoughts(events) if t.get("kind") == "reasoning")
    assert reasoning["text"] == "The dashboard route has no layout."


def test_a_streamed_thought_is_not_replayed_afterwards(architect_turn):
    """The post-hoc replay exists for paths that buffer. Leaving the flag
    unset on a branch that streams would show every chunk twice."""
    g, project, _ = architect_turn
    events = _collect(g._handle_smith_turn(project, "build the dashboard at /"))
    texts = [t.get("text") for t in _thoughts(events) if t.get("kind") == "reasoning"]
    assert len(texts) == len(set(texts)) == 1
