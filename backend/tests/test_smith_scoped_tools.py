"""Tests for the ``scoped_tools=`` parameter on ``run_smith_agent``.

Phase 0 change: when the intent classifier is confident, only the
subset of tools it names should be visible to the LLM AND enforced at
dispatch. Verifies both directions:

  1. The catalog list passed to ``query_fn`` (the LLM stream boundary)
     is filtered to the subset.
  2. If a bogus / wrong-scope tool is dispatched anyway (e.g. by a
     model hallucinating a tool name it didn't see), Smith injects a
     ToolResult error instead of executing it, and keeps looping.

The tests inject a canned stream via ``query_fn`` so no live LLM call
happens.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from agents.smith_agent import run_smith_agent
from services import smith_tools


def _canned_stream(steps: list[dict]):
    """Return a query_fn matching Smith's stream boundary signature.

    The real boundary is ``fn(system_prompt, messages, tool_catalog) -> Iterable[dict]``.
    We capture the received tool_catalog on the returned closure so
    tests can inspect what the LLM was actually offered.
    """
    captured: dict = {"tool_catalog": None}

    def _fn(system_prompt: str, messages: list[dict], tool_catalog: list[dict]) -> Iterator[dict]:
        captured["tool_catalog"] = tool_catalog
        for s in steps:
            yield s

    _fn.captured = captured  # type: ignore[attr-defined]
    return _fn


class TestScopedToolCatalog:
    def test_catalog_filtered_when_scoped_tools_set(self, tmp_path):
        """When scoped_tools is set, the LLM stream receives ONLY that subset."""
        subset = ["answer", "ask_user", "recall"]
        stream = _canned_stream([{"tool": "answer", "args": {"text": "hi"}}])
        run_smith_agent(
            user_message="hey",
            output_dir=str(tmp_path),
            recall_block="",
            query_fn=stream,
            scoped_tools=subset,
        )
        received = stream.captured["tool_catalog"]
        names = {t["name"] for t in received}
        assert names == set(subset), (
            f"expected {subset}, got {sorted(names)}"
        )

    def test_no_scoping_gives_full_catalog(self, tmp_path):
        """When scoped_tools=None, the LLM sees the full catalog."""
        stream = _canned_stream([{"tool": "answer", "args": {"text": "hi"}}])
        run_smith_agent(
            user_message="hey",
            output_dir=str(tmp_path),
            recall_block="",
            query_fn=stream,
            scoped_tools=None,
        )
        received = stream.captured["tool_catalog"]
        assert len(received) == len(smith_tools.TOOL_CATALOG)


class TestScopingDispatchGuard:
    def test_out_of_scope_tool_call_is_refused(self, tmp_path):
        """Even if the LLM emits a tool name not in the subset, dispatch
        refuses it with an educational error instead of executing it."""
        subset = ["answer", "ask_user"]
        stream = _canned_stream([
            # LLM hallucinates an out-of-scope tool call:
            {"tool": "edit_page", "args": {"path": "/x", "instruction": "..."}},
            # Then falls back to answer:
            {"tool": "answer", "args": {"text": "OK let me clarify"}},
        ])
        result = run_smith_agent(
            user_message="hey",
            output_dir=str(tmp_path),
            recall_block="",
            query_fn=stream,
            scoped_tools=subset,
        )
        # The trace records the out-of-scope refusal:
        trace = result["trace"]
        refused = [t for t in trace if "scoped" in str(t.get("result_summary", ""))]
        assert refused, f"expected a scoped-refusal trace entry, got {trace}"
        # And Smith still reached its answer terminal — the wrong-tool
        # attempt didn't derail the loop:
        assert result["answer"] is not None

    def test_in_scope_tool_call_passes_through(self, tmp_path):
        """A tool call inside the subset is dispatched normally."""
        subset = ["answer", "ask_user"]
        stream = _canned_stream([{"tool": "answer", "args": {"text": "hi"}}])
        result = run_smith_agent(
            user_message="hi",
            output_dir=str(tmp_path),
            recall_block="",
            query_fn=stream,
            scoped_tools=subset,
        )
        # No scoped-refusal in the trace:
        trace = result["trace"]
        refused = [t for t in trace if "scoped" in str(t.get("result_summary", ""))]
        assert not refused
        assert result["answer"] == "hi"
