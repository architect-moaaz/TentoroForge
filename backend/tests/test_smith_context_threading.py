"""Tests for the Smith conversation-threading + mutation-guard fixes.

Two behaviors are the point:

1. Prior chat turns thread as real messages, not a flat bullet dump —
   so "did you fix it?" naturally refers to the prior turn.
2. Smith refuses ``answer("Done!")`` when the user asked for a change
   and no mutating tool was called.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

class _FakeConversation:
    """Duck-typed Conversation row for the async session fake."""
    def __init__(self, role, content, message_type, created_at):
        self.role = role
        self.content = content
        self.message_type = message_type
        self.created_at = created_at


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeSession:
    """Minimal async-session fake — captures the query and returns
    scripted rows. Sufficient for load_chat_history_for_prompt."""

    def __init__(self, rows):
        self._rows = rows
        self.last_query = None

    async def execute(self, stmt):
        self.last_query = stmt
        return _FakeResult(self._rows)


def _row(role_value, content, offset_seconds=0):
    """Build a fake row with duck-typed .role.value shape."""
    import datetime as _dt
    fake_role = SimpleNamespace(value=role_value)
    return _FakeConversation(
        role=fake_role,
        content=content,
        message_type=SimpleNamespace(value="chat"),
        created_at=_dt.datetime(2026, 7, 28, 15, 0, 0) - _dt.timedelta(seconds=offset_seconds),
    )


# --------------------------------------------------------------------------- #
# load_chat_history_for_prompt                                                 #
# --------------------------------------------------------------------------- #

class TestLoadChatHistoryForPrompt:
    @pytest.mark.asyncio
    async def test_returns_prior_turns_in_chronological_order(self):
        from services.smith_memory import load_chat_history_for_prompt
        # DB returns newest-first
        sess = _FakeSession([
            _row("user", "did you fix it?", offset_seconds=0),
            _row("assistant", "Done! I removed the fields.", offset_seconds=60),
            _row("user", "remove Department field from /employees/new", offset_seconds=120),
        ])
        import uuid
        out = await load_chat_history_for_prompt(
            sess, uuid.uuid4(), "did you fix it?", limit=6,
        )
        # Should exclude the newest user row (matches current message)
        # and reverse the rest to chronological order.
        assert out == [
            {"role": "user", "content": "remove Department field from /employees/new"},
            {"role": "assistant", "content": "Done! I removed the fields."},
        ]

    @pytest.mark.asyncio
    async def test_drops_current_message_only_when_it_matches(self):
        from services.smith_memory import load_chat_history_for_prompt
        # Newest row is user="hello" — different from current
        # "something else" → do NOT drop.
        # Order: DB newest-first is [user "hello", assistant "hi",
        # user "prior ask"]. After reversing to chronological we get
        # [user "prior ask", assistant "hi", user "hello"], which
        # already starts with user + alternates.
        sess = _FakeSession([
            _row("user", "hello", offset_seconds=0),
            _row("assistant", "hi", offset_seconds=60),
            _row("user", "prior ask", offset_seconds=120),
        ])
        import uuid
        out = await load_chat_history_for_prompt(
            sess, uuid.uuid4(), "something else", limit=6,
        )
        # Current didn't match "hello", so nothing dropped from the tail.
        assert [m["role"] for m in out] == ["user", "assistant", "user"]
        assert out[-1]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_starts_with_user_role(self):
        from services.smith_memory import load_chat_history_for_prompt
        # DB tail begins with an assistant row (no earlier user turn):
        # after chronological reverse this would be role=assistant first.
        # The loader must drop leading assistant rows so alternation
        # starts with user.
        sess = _FakeSession([
            _row("assistant", "welcome message", offset_seconds=0),
        ])
        import uuid
        out = await load_chat_history_for_prompt(
            sess, uuid.uuid4(), "user asks something", limit=6,
        )
        assert out == []  # nothing valid — leading assistant dropped

    @pytest.mark.asyncio
    async def test_collapses_consecutive_same_role_runs(self):
        from services.smith_memory import load_chat_history_for_prompt
        # Two user turns in a row → keep only the newest of the run so
        # alternation is preserved (Anthropic rejects adjacent same-role).
        sess = _FakeSession([
            _row("user", "and one more thing", offset_seconds=0),
            _row("user", "please also add X", offset_seconds=30),
            _row("assistant", "sure, here's the change", offset_seconds=60),
            _row("user", "hey", offset_seconds=120),
        ])
        import uuid
        out = await load_chat_history_for_prompt(
            sess, uuid.uuid4(), "current turn", limit=6,
        )
        # Chronological (oldest first): user "hey" → assistant → user run
        # (collapsed to newest "and one more thing")
        assert [m["role"] for m in out] == ["user", "assistant", "user"]
        assert out[2]["content"] == "and one more thing"

    @pytest.mark.asyncio
    async def test_returns_empty_on_db_failure(self):
        from services.smith_memory import load_chat_history_for_prompt
        class _Broken:
            async def execute(self, stmt):
                raise RuntimeError("db down")
        import uuid
        out = await load_chat_history_for_prompt(
            _Broken(), uuid.uuid4(), "hi", limit=6,
        )
        assert out == []

    @pytest.mark.asyncio
    async def test_respects_limit_after_dropping_current(self):
        from services.smith_memory import load_chat_history_for_prompt
        rows = [
            _row("user", "current message", offset_seconds=0),  # will be dropped
        ]
        for i in range(10):
            rows.append(_row(
                "assistant" if i % 2 == 0 else "user",
                f"turn {i}",
                offset_seconds=30 * (i + 1),
            ))
        sess = _FakeSession(rows)
        import uuid
        out = await load_chat_history_for_prompt(
            sess, uuid.uuid4(), "current message", limit=6,
        )
        # We asked for limit=6 → at most 6 kept, then collapsed for
        # role alternation. Verify no more than 6 threaded.
        assert len(out) <= 6

    @pytest.mark.asyncio
    async def test_clips_oversize_content(self):
        from services.smith_memory import load_chat_history_for_prompt
        long_content = "x" * 10000
        sess = _FakeSession([
            _row("assistant", long_content, offset_seconds=60),
            _row("user", "prior ask", offset_seconds=120),
        ])
        import uuid
        out = await load_chat_history_for_prompt(
            sess, uuid.uuid4(), "current", limit=6,
        )
        assert any(m["content"].endswith("…") for m in out)


# --------------------------------------------------------------------------- #
# _is_mutation_intent                                                          #
# --------------------------------------------------------------------------- #

class TestIsMutationIntent:
    def test_strong_verbs_fire(self):
        from agents.smith_agent import _is_mutation_intent
        assert _is_mutation_intent("remove Department and Role fields from /employees/new")
        assert _is_mutation_intent("add a new Salary field to Employee")
        assert _is_mutation_intent("rename Task to WorkItem")
        assert _is_mutation_intent("delete the /candidates/[id]/reject route")

    def test_question_follow_ups_dont_fire(self):
        from agents.smith_agent import _is_mutation_intent
        # These are anaphora questions — Smith should ANSWER, not
        # fabricate another mutation. False = guard doesn't force edit.
        assert not _is_mutation_intent("did you fix it?")
        assert not _is_mutation_intent("does it work now?")
        assert not _is_mutation_intent("have you already changed it?")
        assert not _is_mutation_intent("can you check?")

    def test_soft_verbs_require_target(self):
        from agents.smith_agent import _is_mutation_intent
        # Soft verb alone → not enough
        assert not _is_mutation_intent("change my mind")
        assert not _is_mutation_intent("fix it later")
        # Soft verb + route/filename/capitalized entity → mutation
        assert _is_mutation_intent("change the label on /login")
        assert _is_mutation_intent("update Department's description")
        assert _is_mutation_intent("fix the dashboard.json layout")

    def test_conversational_no_verb(self):
        from agents.smith_agent import _is_mutation_intent
        # Pure discussion — no mutation verb, no fire.
        assert not _is_mutation_intent("what does this page do?")
        assert not _is_mutation_intent("thanks!")
        assert not _is_mutation_intent("how does the workflow engine work?")

    def test_empty_and_garbage(self):
        from agents.smith_agent import _is_mutation_intent
        assert not _is_mutation_intent("")
        assert not _is_mutation_intent("   ")
        assert not _is_mutation_intent(None)  # type: ignore[arg-type]
