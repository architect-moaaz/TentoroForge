"""Tests for the self-healing orchestrator's pure functions —
prompt synthesis + chat-message formatting. The end-to-end DB path
is covered by the ingest smoke test."""
from __future__ import annotations

import uuid

from services.self_healing import (
    _format_chat_message,
    _synthesize_smith_prompt,
)


_UUID_CRASH_EXC = {
    "id": uuid.uuid4(),
    "project_id": uuid.uuid4(),
    "kind": "workflow",
    "message": 'invalid input syntax for type uuid: ""',
    "stack": None,
    "source_file": "src/lib/workflows/index.ts",
    "source_line": 473,
    "workflow_id": "appointmentstatusworkflow",
    "node_id": "update_status",
    "page_route": None,
    "request_url": None,
    "request_method": None,
    "occurrence_count": 3,
    "heal_attempts": 1,
}


# =========================================================================
# _synthesize_smith_prompt — the prompt Smith actually sees
# =========================================================================

def test_synthesize_includes_error_message_and_locator():
    prompt = _synthesize_smith_prompt(_UUID_CRASH_EXC)
    assert 'invalid input syntax for type uuid: ""' in prompt
    assert "src/lib/workflows/index.ts:473" in prompt
    assert "appointmentstatusworkflow" in prompt
    assert "update_status" in prompt


def test_synthesize_instructs_direct_edit_not_seam():
    prompt = _synthesize_smith_prompt(_UUID_CRASH_EXC)
    assert "read_file" in prompt
    assert "edit_file" in prompt
    assert "verify_promise" in prompt
    # The prompt must forbid propose_fix on runtime-crash healing (a seam
    # patch card is wrong when the runtime file itself needs editing).
    # Accepts either phrasing since the rule matters more than the exact words.
    lowered = prompt.lower()
    assert ("do not propose" in lowered
            or "not propose" in lowered
            or "do not call `propose_fix`" in lowered), (
        "runtime-exception prompt must forbid propose_fix"
    )


def test_synthesize_reports_occurrence_count_when_gt_one():
    prompt = _synthesize_smith_prompt(_UUID_CRASH_EXC)
    assert "Seen:    3 times" in prompt


def test_synthesize_omits_missing_locators():
    """When the exception has no page_route / request_url, those lines
    stay out of the prompt so it doesn't lead Smith down a wrong path."""
    exc = dict(_UUID_CRASH_EXC)
    prompt = _synthesize_smith_prompt(exc)
    assert "Page:" not in prompt
    assert "Request:" not in prompt


def test_synthesize_includes_stack_when_provided():
    exc = dict(_UUID_CRASH_EXC, stack="at db_update (line 473)\nat handler (…)")
    prompt = _synthesize_smith_prompt(exc)
    assert "Stack:" in prompt
    assert "at db_update" in prompt


def test_synthesize_truncates_huge_stacks():
    exc = dict(_UUID_CRASH_EXC, stack="x" * 10_000)
    prompt = _synthesize_smith_prompt(exc)
    assert "[truncated]" in prompt


# =========================================================================
# _format_chat_message — user-visible outcome
# =========================================================================

def test_format_message_resolved_names_files_and_commit():
    text = _format_chat_message(
        _UUID_CRASH_EXC,
        smith_result={
            "answer": "Fixed the WHERE resolver to coerce empty refs.",
            "edited_paths": ["src/lib/workflows/index.ts"],
        },
        commit="abc123def456",
    )
    assert "resolved" in text.lower()
    assert "abc123def456" in text
    assert "src/lib/workflows/index.ts" in text
    assert "Fixed the WHERE resolver" in text


def test_format_message_asks_for_input_when_smith_asks_a_question():
    text = _format_chat_message(
        _UUID_CRASH_EXC,
        smith_result={"question": "Should this coerce to null or throw?"},
        commit=None,
    )
    assert "needs your input" in text.lower()
    assert "Should this coerce" in text


def test_format_message_reports_no_fix_when_no_edits():
    text = _format_chat_message(
        _UUID_CRASH_EXC,
        smith_result={"answer": "Couldn't localize the fix."},
        commit=None,
    )
    assert "no fix produced" in text.lower()
    assert "Couldn't localize" in text
