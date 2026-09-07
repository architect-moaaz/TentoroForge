"""Smith agent — reasoning loop with injected query_fn (no real model calls).

Structural fork of test_fix_chat_agent — the tests verify the three
terminal shapes (propose_fix / answer / ask_user), memory-block threading,
tool dispatch, and iteration-cap safety.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents import smith_agent


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #

def _canned(*steps):
    """Return a query_fn that emits the given steps in order and stops."""
    def _fn(system_prompt, messages, tool_catalog):
        for step in steps:
            yield step
    return _fn


def _dummy_output_dir(tmp_path: Path) -> str:
    """A minimal output_dir with just the registry (enough for validators
    that read contracts/resource-registry.json to not crash)."""
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({
        "entities": [{"name": "Widget", "columns": [
            {"name": "id", "sqlType": "uuid"},
            {"name": "name", "sqlType": "text"},
        ]}],
        "relationships": [],
        "roles": [],
        "interactions": [],
    }), encoding="utf-8")
    return str(tmp_path)


# --------------------------------------------------------------------------- #
# Terminal: answer  — Smith replies without proposing a fix
# --------------------------------------------------------------------------- #

def test_answer_terminal_populates_answer_key(tmp_path):
    out = _dummy_output_dir(tmp_path)
    result = smith_agent.run_smith_agent(
        "How does the Schedule button work?",
        out,
        recall_block="APP INTENT: ATS",
        memory_block="",
        query_fn=_canned({"tool": "answer", "args": {
            "text": "The Schedule button triggers the AssessmentScheduling workflow, "
                    "which inserts an assessments row and notifies both the candidate "
                    "and the assessor.",
        }}),
    )
    assert result["diagnosis"] is None
    assert result["question"] is None
    assert result["answer"] is not None
    assert "AssessmentScheduling" in result["answer"]
    assert result["trace"][-1]["tool"] == "answer"


def test_answer_with_empty_text_is_retried_not_accepted(tmp_path):
    """If the model calls answer with empty/missing text, the loop should
    push back and give it another chance instead of finalizing garbage."""
    out = _dummy_output_dir(tmp_path)
    result = smith_agent.run_smith_agent(
        "explain",
        out,
        recall_block="",
        memory_block="",
        query_fn=_canned(
            {"tool": "answer", "args": {}},  # invalid
            {"tool": "answer", "args": {"text": "Second try — this one works."}},
        ),
    )
    assert result["answer"] == "Second try — this one works."
    assert any("invalid answer" in t["result_summary"] for t in result["trace"])


# --------------------------------------------------------------------------- #
# Terminal: ask_user
# --------------------------------------------------------------------------- #

def test_ask_user_populates_question_key(tmp_path):
    out = _dummy_output_dir(tmp_path)
    result = smith_agent.run_smith_agent(
        "it's broken",
        out,
        recall_block="",
        memory_block="",
        query_fn=_canned({"tool": "ask_user", "args": {
            "question": "Which screen were you on when it broke?",
        }}),
    )
    assert result["question"] == "Which screen were you on when it broke?"
    assert result["diagnosis"] is None
    assert result["answer"] is None


# --------------------------------------------------------------------------- #
# Terminal: propose_fix — reuses fix_chat_agent's validator
# --------------------------------------------------------------------------- #

def test_propose_fix_terminal_populates_diagnosis(tmp_path):
    """A well-formed page_schema_patch proposal should flow through
    validation and populate diagnosis (workflow_node_config is exercised
    heavily in test_fix_chat_agent; we cover the OTHER seam here to
    prove Smith isn't fix-workflow-only)."""
    out = _dummy_output_dir(tmp_path)
    result = smith_agent.run_smith_agent(
        "Add a Tag to the widget page",
        out,
        recall_block="APP INTENT: ATS",
        memory_block="",
        query_fn=_canned({"tool": "propose_fix", "args": {"diagnosis": {
            "feature": "widget-detail",
            "rootCause": "no status badge",
            "artifact": {"kind": "page", "path": "app/widgets/page.json"},
            "locator": {"nodeId": None, "jsonPointer": "/content/0/children"},
            "proposedFix": {
                "seam": "page_schema_patch",
                "patch": [{"op": "add", "path": "/content/0/children/-",
                           "value": {"type": "Tag", "props": {"label": "Active"}}}],
            },
            "confidence": 0.9,
            "explanation": "Will add an Active tag next to the title.",
        }}}),
    )
    assert result["diagnosis"] is not None
    assert result["diagnosis"]["proposedFix"]["seam"] == "page_schema_patch"
    assert result["diagnosis"]["confidence"] == 0.9
    assert result["answer"] is None and result["question"] is None


def test_invalid_diagnosis_is_pushed_back_not_accepted(tmp_path):
    """Bad seam → the loop injects an error and gives the model another
    turn instead of returning a garbage diagnosis."""
    out = _dummy_output_dir(tmp_path)
    result = smith_agent.run_smith_agent(
        "fix it",
        out,
        recall_block="",
        memory_block="",
        query_fn=_canned(
            {"tool": "propose_fix", "args": {"diagnosis": {
                "artifact": {"kind": "workflow", "path": "w.json"},
                "proposedFix": {"seam": "bogus_seam", "patch": {}},
            }}},
            # Second try — valid.
            {"tool": "answer", "args": {"text": "OK let me investigate more."}},
        ),
    )
    # First turn didn't terminate — second did.
    assert result["diagnosis"] is None
    assert result["answer"] is not None
    assert any("invalid diagnosis" in t["result_summary"] for t in result["trace"])


# --------------------------------------------------------------------------- #
# Read-only tool dispatch
# --------------------------------------------------------------------------- #

def test_read_only_tool_is_dispatched_and_result_appended(tmp_path):
    """Calling recall as the first turn should invoke the handler and put
    the result on the trace, THEN allow a subsequent terminal."""
    out = _dummy_output_dir(tmp_path)
    result = smith_agent.run_smith_agent(
        "what's in the app?",
        out,
        recall_block="APP INTENT: ATS",
        memory_block="",
        query_fn=_canned(
            {"tool": "recall", "args": {}},
            {"tool": "answer", "args": {"text": "The app has one entity: Widget."}},
        ),
    )
    tools_seen = [t["tool"] for t in result["trace"]]
    assert tools_seen == ["recall", "answer"]
    assert result["answer"].startswith("The app")


def test_unknown_tool_pushes_back_then_forces_ask_user(tmp_path):
    """Two consecutive unknown tool calls → force ask_user (safety valve)."""
    out = _dummy_output_dir(tmp_path)
    result = smith_agent.run_smith_agent(
        "help",
        out,
        recall_block="",
        memory_block="",
        query_fn=_canned(
            {"tool": "bogus_tool", "args": {}},
            {"tool": "another_fake", "args": {}},
            # Model would get a third turn but the forced ask_user should end things first.
            {"tool": "answer", "args": {"text": "should never see this"}},
        ),
    )
    assert result["question"] is not None, "forced ask_user should populate question"
    assert result["answer"] is None
    assert any(t["tool"] == "ask_user" for t in result["trace"])
    assert any("forced" in json.dumps(t.get("args", {})) for t in result["trace"])


def test_duplicate_read_only_call_is_short_circuited(tmp_path):
    """The live-run trace on a clean app showed Smith re-reading the same
    page 6 times in a row until the iteration cap. Duplicate (tool, args)
    calls should be pushed back with an error so the model picks something
    new — the third call is a completely different tool and should run."""
    out = _dummy_output_dir(tmp_path)
    result = smith_agent.run_smith_agent(
        "what's here?",
        out,
        recall_block="",
        memory_block="",
        query_fn=_canned(
            {"tool": "recall", "args": {}},
            {"tool": "recall", "args": {}},              # duplicate → short-circuited
            {"tool": "read_column",                       # different → runs
             "args": {"entity": "Widget", "column": "id"}},
            {"tool": "answer", "args": {"text": "done"}},
        ),
    )
    tool_names = [t["tool"] for t in result["trace"]]
    assert tool_names == ["recall", "recall", "read_column", "answer"]
    assert "duplicate call" in result["trace"][1]["result_summary"]
    assert result["answer"] == "done"


def test_duplicate_different_args_still_runs(tmp_path):
    """Dedup keys off (tool, args) — same tool with DIFFERENT args is
    still a legitimate second call and must not be short-circuited."""
    out = _dummy_output_dir(tmp_path)
    result = smith_agent.run_smith_agent(
        "read two pages",
        out,
        recall_block="",
        memory_block="",
        query_fn=_canned(
            {"tool": "read_page", "args": {"path": "a.json"}},
            {"tool": "read_page", "args": {"path": "b.json"}},  # DIFFERENT args
            {"tool": "answer", "args": {"text": "ok"}},
        ),
    )
    tool_names = [t["tool"] for t in result["trace"]]
    assert tool_names == ["read_page", "read_page", "answer"]
    # Neither should be marked duplicate.
    for step in result["trace"][:2]:
        assert "duplicate call" not in (step.get("result_summary") or "")


def test_iteration_cap_forces_ask_user(tmp_path):
    """Endless read-only tool calls without a terminal → forced ask_user."""
    out = _dummy_output_dir(tmp_path)

    def _endless_recall(*_):
        while True:
            yield {"tool": "recall", "args": {}}

    result = smith_agent.run_smith_agent(
        "look forever",
        out,
        recall_block="",
        memory_block="",
        query_fn=_endless_recall,
        max_iters=3,
    )
    assert result["question"] is not None
    # Trace should include ~3 recall calls + the forced ask_user.
    tool_names = [t["tool"] for t in result["trace"]]
    assert tool_names.count("recall") == 3
    assert tool_names[-1] == "ask_user"


# --------------------------------------------------------------------------- #
# S7: answer-from-diff hard gate — no "believes he did it"
# --------------------------------------------------------------------------- #

def test_edits_without_matching_verify_helper_semantics():
    """Anchor the helper directly — no LLM in the loop."""
    fn = smith_agent._edits_without_matching_verify
    # No edits at all → safe.
    assert fn([{"tool": "recall"}, {"tool": "read_page"}]) == []
    # Edit then verify_promise → safe.
    assert fn([{"tool": "edit_file"}, {"tool": "verify_promise"}]) == []
    # Edit then run_guards → safe.
    assert fn([{"tool": "edit_page"}, {"tool": "run_guards"}]) == []
    # Edit with no follow-up → refused, names the mutator.
    assert fn([{"tool": "edit_file"}]) == ["edit_file"]
    # Verify BEFORE the edit doesn't count — must be AFTER the last mutation.
    assert fn([
        {"tool": "verify_promise"},
        {"tool": "edit_file"},
    ]) == ["edit_file"]
    # Second edit after a verified first → refused for the second.
    assert fn([
        {"tool": "edit_file"},
        {"tool": "verify_promise"},
        {"tool": "edit_workflow"},
    ]) == ["edit_workflow"]


def test_answer_refused_when_edit_has_no_matching_verify(tmp_path):
    """The classic 'believes he did it' pattern: Smith edits a file then
    claims Done without proving it landed. The loop must reject the
    answer and push the model back for a verify_promise / run_guards."""
    out = _dummy_output_dir(tmp_path)
    # Make a real target so edit_file's I/O doesn't crash the trace shape.
    target = Path(out) / "src" / "schemas" / "candidates" / "new.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"kind":"form","widgets":[]}', encoding="utf-8")

    result = smith_agent.run_smith_agent(
        "Change the CV field to a FileUpload",
        out,
        recall_block="",
        memory_block="",
        query_fn=_canned(
            {"tool": "edit_file", "args": {
                "path": "src/schemas/candidates/new.json",
                "old_string": '{"kind":"form","widgets":[]}',
                "new_string": '{"kind":"form","widgets":[{"component":"FileUpload"}]}',
            }},
            {"tool": "answer", "args": {"text": "Done — changed to FileUpload!"}},
            {"tool": "verify_promise", "args": {
                "path": "src/schemas/candidates/new.json",
                "claim": "widgets contains a FileUpload",
            }},
            {"tool": "answer", "args": {"text": "Verified — FileUpload landed."}},
        ),
    )
    assert result["answer"] == "Verified — FileUpload landed."
    # The premature answer was refused, not swallowed silently.
    refused = [t for t in result["trace"]
               if t["tool"] == "answer" and "answer refused" in (t.get("result_summary") or "")]
    assert len(refused) == 1
    assert "edit_file" in refused[0]["result_summary"]


def test_answer_accepted_immediately_when_no_edits_were_made(tmp_path):
    """Read-only conversations (explain / summarize / greet) must NOT
    be gated — the gate only protects mutation-with-lie."""
    out = _dummy_output_dir(tmp_path)
    result = smith_agent.run_smith_agent(
        "what does this app do?",
        out,
        recall_block="APP INTENT: ATS",
        memory_block="",
        query_fn=_canned(
            {"tool": "recall", "args": {}},
            {"tool": "answer", "args": {"text": "It's an ATS."}},
        ),
    )
    assert result["answer"] == "It's an ATS."
    assert not any(
        "answer refused" in (t.get("result_summary") or "") for t in result["trace"]
    )


# --------------------------------------------------------------------------- #
# Initial-user-message threading
# --------------------------------------------------------------------------- #

def test_initial_user_message_threads_memory_and_recall_blocks():
    msg = smith_agent.build_initial_user_message(
        user_message="hi",
        recall_block="APP INTENT: ATS",
        memory_block="<smith-memory>\n- pending fix from 14:00\n</smith-memory>",
    )
    assert "USER: hi" in msg
    # Memory renders ABOVE recall so a stale-pending signal dominates.
    assert msg.index("<smith-memory>") < msg.index("## App recall")
    assert "pending fix from 14:00" in msg
    assert "APP INTENT: ATS" in msg


def test_empty_memory_still_renders_a_stable_block():
    msg = smith_agent.build_initial_user_message(
        user_message="hi", recall_block="", memory_block="",
    )
    # Even with no memory the block is present so the prompt structure is stable.
    assert "No prior conversation state" in msg


# --------------------------------------------------------------------------- #
# System prompt reflects the live catalog
# --------------------------------------------------------------------------- #

def test_system_prompt_includes_every_tool_from_the_catalog():
    from services import smith_tools
    prompt = smith_agent.build_system_prompt()
    for tool in smith_tools.TOOL_CATALOG:
        assert tool["name"] in prompt, f"catalog tool {tool['name']} missing from prompt"


def test_system_prompt_documents_the_three_terminals():
    prompt = smith_agent.build_system_prompt()
    for terminal in ("propose_fix", "answer", "ask_user"):
        assert terminal in prompt


def test_system_prompt_tells_smith_not_to_apply_himself():
    prompt = smith_agent.build_system_prompt()
    # The wording may vary but the message must be present.
    assert "Apply" in prompt
    assert "NEVER apply" in prompt or "never apply" in prompt.lower()


# --------------------------------------------------------------------------- #
# Result shape — always the same four keys
# --------------------------------------------------------------------------- #

def test_result_always_has_stable_keys(tmp_path):
    """Result shape is stable: the five terminals plus the context keys the
    router relies on (understanding/pending_confirmation/edited_paths). Exactly
    one terminal is populated per run."""
    out = _dummy_output_dir(tmp_path)
    r = smith_agent.run_smith_agent(
        "hi", out, "", "",
        query_fn=_canned({"tool": "answer", "args": {"text": "hello"}}),
    )
    # The five terminals must always be present (the router reads them by name).
    assert {"diagnosis", "answer", "question", "handoff", "trace"} <= set(r.keys())
    populated = [k for k in ("diagnosis", "answer", "question", "handoff") if r[k] is not None]
    assert populated == ["answer"]


# --------------------------------------------------------------------------- #
# Terminal: handoff_to_pipeline
# --------------------------------------------------------------------------- #

def test_handoff_terminal_populates_handoff_key(tmp_path):
    """Smith calls handoff_to_pipeline(kind='discovery', message=…) → result
    carries a handoff dict the router can forward to the pipeline."""
    out = _dummy_output_dir(tmp_path)
    r = smith_agent.run_smith_agent(
        "Build me a patient management system for a clinic",
        out, "", "",
        query_fn=_canned({"tool": "handoff_to_pipeline", "args": {
            "kind": "discovery",
            "message": "Patient management system for a clinic (patients, visits, providers, prescriptions).",
        }}),
    )
    assert r["handoff"] == {
        "kind": "discovery",
        "message": "Patient management system for a clinic (patients, visits, providers, prescriptions).",
    }
    assert r["diagnosis"] is None
    assert r["answer"] is None
    assert r["question"] is None


def test_handoff_with_invalid_kind_is_pushed_back(tmp_path):
    out = _dummy_output_dir(tmp_path)
    r = smith_agent.run_smith_agent(
        "hi", out, "", "",
        query_fn=_canned(
            {"tool": "handoff_to_pipeline", "args": {"kind": "nonsense", "message": "x"}},
            {"tool": "answer", "args": {"text": "OK"}},
        ),
    )
    assert r["handoff"] is None
    assert r["answer"] == "OK"
    assert any("invalid handoff kind" in t["result_summary"] for t in r["trace"])


def test_handoff_with_empty_message_is_pushed_back(tmp_path):
    out = _dummy_output_dir(tmp_path)
    r = smith_agent.run_smith_agent(
        "hi", out, "", "",
        query_fn=_canned(
            {"tool": "handoff_to_pipeline", "args": {"kind": "discovery", "message": "   "}},
            {"tool": "answer", "args": {"text": "OK"}},
        ),
    )
    assert r["handoff"] is None
    assert r["answer"] == "OK"


# --------------------------------------------------------------------------- #
# Extended thinking — reasoning_callback threading + model-gating +
# env-var toggle + backward-compat with injected query_fns
# --------------------------------------------------------------------------- #

def test_model_supports_thinking_gating():
    """Prefix-match helper: sonnet-4.5+ / sonnet-4.6 / sonnet-5 / opus-4 /
    opus-5 / fable-5 pass; older sonnet-3, opus-3, haiku-4 must not."""
    from agents.fix_chat_agent import _model_supports_thinking
    assert _model_supports_thinking("claude-sonnet-4-5-20260101")
    assert _model_supports_thinking("claude-sonnet-4-6")
    assert _model_supports_thinking("claude-sonnet-5-20260210")
    assert _model_supports_thinking("claude-opus-4")
    assert _model_supports_thinking("claude-opus-5-20260301")
    assert _model_supports_thinking("claude-fable-5")
    # Non-thinking families
    assert not _model_supports_thinking("claude-haiku-4")
    assert not _model_supports_thinking("claude-sonnet-3-5")
    assert not _model_supports_thinking("claude-opus-3-7")
    assert not _model_supports_thinking("")
    assert not _model_supports_thinking(None)  # type: ignore[arg-type]


def test_thinking_block_matches_what_the_model_accepts():
    """`budget_tokens` is rejected outright from the 4.7 generation on, and
    `adaptive` is not understood before 4.6. Sending the wrong one is a 400
    that names neither the model nor the block."""
    from agents.fix_chat_agent import THINKING_HEADROOM_TOKENS, _thinking_block

    assert _thinking_block("claude-sonnet-4-6") == {"type": "adaptive"}
    assert _thinking_block("claude-opus-5-20260301") == {"type": "adaptive"}
    assert _thinking_block("claude-sonnet-4-5-20260101") == {
        "type": "enabled", "budget_tokens": THINKING_HEADROOM_TOKENS}
    # The only reason for no thinking is a model that has none.
    assert _thinking_block("claude-haiku-4-5") is None


def test_thinking_is_not_behind_a_switch():
    """It was, defaulting to off — so the reasoning stream, the SSE event and
    the frontend renderer all worked and emitted nothing. A capability whose
    off-position is silent is indistinguishable from a broken one."""
    import inspect

    from agents import fix_chat_agent

    src = inspect.getsource(fix_chat_agent._thinking_block)
    assert "environ" not in src and "getenv" not in src
    assert not hasattr(fix_chat_agent, "_thinking_budget")


def test_one_table_says_what_a_model_accepts():
    """The agent and the one-shot transport both ask this question. Two prefix
    tables drift the first time one is updated for a new release, and the
    symptom is a 400 from whichever call site was missed."""
    from agents import fix_chat_agent
    from services import llm_client

    assert fix_chat_agent._thinking_block is llm_client.thinking_block_for
    assert fix_chat_agent._model_supports_thinking is llm_client.supports_thinking


def _mock_anthropic_response(*, thinking_texts, text_payload):
    """Build a stand-in for anthropic's msg.content — a mix of thinking
    blocks (attr `.thinking`) and text blocks (attr `.text`), the same
    shape the real SDK returns for extended-thinking calls."""
    class _T:
        def __init__(self, s): self.thinking = s
    class _X:
        def __init__(self, s): self.text = s
    content = [_T(t) for t in thinking_texts] + [_X(text_payload)]
    class _Msg:
        pass
    m = _Msg()
    m.content = content
    return m


def _install_fake_anthropic(monkeypatch, *, on_create):
    """Stub the LLM client boundary. Since the LangGraph migration (LG-1),
    the fix/smith agents build their client via services.llm_client — patch
    its Anthropic factory (NOT sys.modules["anthropic"], which would poison
    langchain_anthropic's own internal imports)."""
    from services import llm_client

    class _FakeMessages:
        def create(self, **kwargs):
            return on_create(**kwargs)

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr(llm_client, "Anthropic", lambda **_kw: _FakeClient())


def test_default_query_forwards_thinking_blocks_to_reasoning_callback(monkeypatch):
    """The mocked SDK returns a response with two ThinkingBlocks then a
    TextBlock containing the tool-call JSON. `_default_query` must call
    the reasoning callback once per thinking block, then yield the parsed
    tool call."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    from agents import fix_chat_agent

    captured: dict = {}
    fake_msg = _mock_anthropic_response(
        thinking_texts=[
            "Let me look at the app plan first…",
            "The Schedule button triggers AssessmentScheduling.",
        ],
        text_payload='{"tool":"recall","args":{}}',
    )

    def _on_create(**kwargs):
        captured.update(kwargs)
        return fake_msg

    _install_fake_anthropic(monkeypatch, on_create=_on_create)

    reasoning: list[str] = []
    stream = fix_chat_agent._default_query(
        "sys", [{"role": "user", "content": "hi"}], [],
        reasoning_callback=reasoning.append,
    )
    first = next(iter(stream))
    assert first == {"tool": "recall", "args": {}}
    assert reasoning == [
        "Let me look at the app plan first…",
        "The Schedule button triggers AssessmentScheduling.",
    ]
    # The thinking block was actually sent to the API.
    # sonnet-4-6 takes the adaptive form; `budget_tokens` is deprecated
    # there and a 400 from 4.7 on.
    assert captured.get("thinking") == {"type": "adaptive"}
    assert captured.get("temperature") == 1.0
    assert captured.get("max_tokens", 0) >= 1500 + 4096


def test_default_query_sends_no_thinking_block_to_a_model_without_it(monkeypatch):
    """Haiku and the pre-4.5 families have no extended thinking. That is the
    only reason a request goes out without the block."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    from agents import fix_chat_agent

    # The seam the call site actually consults. `_model_supports_thinking` is
    # now an import from services.llm_client, and patching the local alias
    # would not reach the function that reads it.
    monkeypatch.setattr(fix_chat_agent, "_thinking_block", lambda _m: None)

    captured: dict = {}
    fake_msg = _mock_anthropic_response(
        thinking_texts=[],
        text_payload='{"tool":"answer","args":{"text":"hi"}}',
    )

    def _on_create(**kwargs):
        captured.update(kwargs)
        return fake_msg

    _install_fake_anthropic(monkeypatch, on_create=_on_create)

    reasoning: list[str] = []
    stream = fix_chat_agent._default_query(
        "sys", [{"role": "user", "content": "hi"}], [],
        reasoning_callback=reasoning.append,
    )
    step = next(iter(stream))
    assert step == {"tool": "answer", "args": {"text": "hi"}}
    assert "thinking" not in captured
    # temperature is left unset (defaults on the API side) — thinking-off
    assert "temperature" not in captured
    # max_tokens stays at the classic 1500 (no thinking headroom needed)
    assert captured.get("max_tokens") == 1500
    assert reasoning == []


def test_run_smith_agent_forwards_reasoning_callback_to_default_query(monkeypatch, tmp_path):
    """When the caller passes reasoning_callback AND no custom query_fn,
    run_smith_agent must wrap _default_query so the callback reaches it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    fake_msg = _mock_anthropic_response(
        thinking_texts=["thinking about it…"],
        text_payload='{"tool":"answer","args":{"text":"Hello!"}}',
    )
    _install_fake_anthropic(monkeypatch, on_create=lambda **_kw: fake_msg)

    out = _dummy_output_dir(tmp_path)
    reasoning: list[str] = []
    r = smith_agent.run_smith_agent(
        "hi", out, "", "",
        reasoning_callback=reasoning.append,
    )
    assert r["answer"] == "Hello!"
    assert reasoning == ["thinking about it…"]


def test_injected_query_fn_still_works_without_reasoning_callback(tmp_path):
    """Backward-compat: tests that inject a canned query_fn (3-arg sig)
    must keep working; the reasoning callback is not required."""
    out = _dummy_output_dir(tmp_path)
    r = smith_agent.run_smith_agent(
        "hi", out, "", "",
        query_fn=_canned({"tool": "answer", "args": {"text": "OK"}}),
    )
    assert r["answer"] == "OK"


def test_injected_query_fn_takes_precedence_over_reasoning_callback(tmp_path):
    """When both a query_fn AND a reasoning_callback are given, the
    injected query_fn wins (tests never hit the model boundary). The
    callback is silently dropped in that case — a test suite that
    injects a query_fn is intentionally bypassing the real SDK path."""
    out = _dummy_output_dir(tmp_path)
    got: list[str] = []
    r = smith_agent.run_smith_agent(
        "hi", out, "", "",
        query_fn=_canned({"tool": "answer", "args": {"text": "OK"}}),
        reasoning_callback=got.append,
    )
    assert r["answer"] == "OK"
    assert got == []  # canned iterator never triggers thinking


def test_progress_callback_fires_tool_start_for_non_terminals(tmp_path):
    """`progress_callback` should fire ONCE per non-terminal tool call
    with phase=tool_start, before the tool actually dispatches. This is
    what the SSE-streaming path in `_handle_smith_turn` reads to render
    the live "Reading X…" chips. Terminals (answer/ask_user/propose_fix/
    handoff_to_pipeline) MUST be skipped — the outer terminal event
    already narrates them and a chip would double-render right before
    the actual answer.
    """
    out = _dummy_output_dir(tmp_path)
    events: list[dict] = []

    smith_agent.run_smith_agent(
        "what's up",
        out,
        recall_block="",
        memory_block="",
        query_fn=_canned(
            {"tool": "recall", "args": {}},
            {"tool": "list_pages", "args": {}},
            {"tool": "answer", "args": {"text": "Two pages."}},
        ),
        progress_callback=events.append,
    )

    # Two non-terminal tools fired → two tool_start events, in order.
    starts = [e for e in events if e.get("phase") == "tool_start"]
    tool_names = [e.get("tool") for e in starts]
    assert tool_names == ["recall", "list_pages"], f"unexpected: {tool_names}"
    # `answer` is a terminal and must NOT get a tool_start chip.
    assert "answer" not in tool_names
    # Payload shape: each event carries the trimmed args.
    for e in starts:
        assert "args" in e and isinstance(e["args"], dict)


def test_progress_callback_exception_does_not_break_the_loop(tmp_path):
    """A callback that raises must not derail Smith. The turn is
    authoritative; UI wiring is best-effort."""
    out = _dummy_output_dir(tmp_path)

    def _boom(_evt):
        raise RuntimeError("frontend went away")

    r = smith_agent.run_smith_agent(
        "what's up", out, "", "",
        query_fn=_canned(
            {"tool": "recall", "args": {}},
            {"tool": "answer", "args": {"text": "still here"}},
        ),
        progress_callback=_boom,
    )
    assert r["answer"] == "still here"
    assert [t["tool"] for t in r["trace"]] == ["recall", "answer"]
