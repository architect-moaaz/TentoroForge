"""Tests for the Smith reward/punishment ledger (smith_outcomes) and its
agent-loop + orchestrator hooks (2026-08-19)."""
from __future__ import annotations

import json
from typing import Iterator

from services import smith_outcomes as so
from agents.smith_agent import run_smith_agent


# ── Ledger core ──────────────────────────────────────────────────────────

def test_record_and_scoreboard(tmp_path):
    d = str(tmp_path)
    so.record_outcome(d, tool="edit_page", signal="apply_ok",
                      intent_kind="style", turn=1)
    so.record_outcome(d, tool="edit_page", signal="verified",
                      intent_kind="style", turn=1)
    so.record_outcome(d, tool="add_page", signal="apply_error",
                      intent_kind="build", evidence="validator said no", turn=2)
    board = so.scoreboard(d)
    assert board[("style", "edit_page")]["score"] == 3   # +1 +2
    assert board[("build", "add_page")]["score"] == -2
    assert board[("build", "add_page")]["last_fail"] == "validator said no"


def test_turn_ids_monotonic(tmp_path):
    d = str(tmp_path)
    assert so.next_turn_id(d) == 1
    so.record_outcome(d, tool="x", signal="apply_ok", turn=1)
    assert so.next_turn_id(d) == 2
    last, entries = so.last_turn_entries(d)
    assert last == 1 and len(entries) == 1


def test_classify_intent_kind():
    assert so.classify_intent_kind("fix the broken save button") == "fix"
    assert so.classify_intent_kind("change the theme color to blue") == "style"
    assert so.classify_intent_kind("add a new page for invoices") == "build"
    assert so.classify_intent_kind("add a dropdown field to the form") == "data"
    assert so.classify_intent_kind("hello") == "other"


# ── Chat-native feedback ─────────────────────────────────────────────────

def test_sentiment_detection():
    assert so.score_user_message("perfect, thanks!")[0] == "user_praise"
    assert so.score_user_message("it still doesn't work")[0] == "user_complaint"
    # complaint wins when both present
    assert so.score_user_message("thanks but it's still broken")[0] == "user_complaint"
    assert so.score_user_message("now add a chart")[0] is None


def test_re_ask_detection():
    prev = "make the status field a dropdown on the candidates page"
    assert so.is_re_ask(prev, "please make the status field a dropdown")
    assert not so.is_re_ask(prev, "add a chart to the dashboard")


def test_apply_feedback_complaint_punishes_last_turn(tmp_path):
    d = str(tmp_path)
    so.record_outcome(d, tool="edit_page", signal="apply_ok",
                      intent_kind="style", intent_text="make header blue", turn=1)
    out = so.apply_feedback_to_last_turn(d, "that didn't work, it's still white")
    assert out["applied"] == "user_complaint"
    board = so.scoreboard(d)
    assert board[("style", "edit_page")]["score"] == 1 - 3


def test_apply_feedback_re_ask(tmp_path):
    d = str(tmp_path)
    so.record_outcome(d, tool="edit_page", signal="apply_ok",
                      intent_kind="style",
                      intent_text="make the header background blue", turn=1)
    out = so.apply_feedback_to_last_turn(d, "make the header background blue")
    assert out["applied"] == "re_ask"


def test_apply_feedback_noop_without_signal(tmp_path):
    d = str(tmp_path)
    so.record_outcome(d, tool="edit_page", signal="apply_ok",
                      intent_kind="style", intent_text="blue header", turn=1)
    assert so.apply_feedback_to_last_turn(d, "now add a totally new invoices page")["applied"] is None


# ── Playbook rendering ───────────────────────────────────────────────────

def test_playbook_sections_and_consequences(tmp_path):
    d = str(tmp_path)
    for _ in range(3):
        so.record_outcome(d, tool="add_page", signal="verified",
                          intent_kind="build", turn=1)
    so.record_outcome(d, tool="edit_page", signal="regression",
                      intent_kind="style", evidence="guards went red", turn=2)
    block = so.render_playbook(d)
    assert "PROVEN MOVES" in block and "build via add_page" in block
    assert "PUNISHED MOVES" in block and "style via edit_page" in block
    assert "guards went red" in block
    assert "MUST" in block  # binding consequence rule


def test_playbook_empty_ledger(tmp_path):
    assert so.render_playbook(str(tmp_path)) == ""


# ── Agent-loop integration (canned LLM) ──────────────────────────────────

def _canned_stream(steps):
    def _fn(system_prompt: str, messages, tool_catalog) -> Iterator[dict]:
        _fn.system_prompt = system_prompt
        _fn.memory_seen = "".join(
            m.get("content", "") for m in messages if isinstance(m, dict))
        for s in steps:
            yield s
    return _fn


def test_agent_records_readonly_free_answer_no_ledger(tmp_path):
    stream = _canned_stream([{"tool": "answer", "args": {"text": "hi"}}])
    run_smith_agent(user_message="hey", output_dir=str(tmp_path),
                    recall_block="", query_fn=stream)
    # answering without mutating writes nothing to the ledger
    assert so.scoreboard(str(tmp_path)) == {}


def test_agent_injects_playbook_into_context(tmp_path):
    d = str(tmp_path)
    so.record_outcome(d, tool="edit_page", signal="regression",
                      intent_kind="style", evidence="broke the header", turn=1)
    stream = _canned_stream([{"tool": "answer", "args": {"text": "hi"}}])
    run_smith_agent(user_message="hey", output_dir=d,
                    recall_block="", query_fn=stream)
    blob = getattr(stream, "memory_seen", "") + getattr(stream, "system_prompt", "")
    assert "smith-playbook" in blob and "PUNISHED MOVES" in blob
