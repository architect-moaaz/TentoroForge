"""Smith memory — cross-turn context assembled from Conversation rows.

Pure builder tests + a mock-session async test. No real DB required.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services.smith_memory import (
    MemoryTurn,
    SmithMemory,
    build_memory_block,
    build_smith_memory,
    derive_state_lines,
    normalize_conversation_rows,
    read_smith_memory,
)


# --------------------------------------------------------------------------- #
# build_memory_block  — pure rendering
# --------------------------------------------------------------------------- #

def test_empty_memory_still_produces_a_stable_block():
    """An empty memory renders a short 'no prior state' block so the model
    sees a consistent structure instead of a missing section."""
    block = build_memory_block([], [])
    assert "<smith-memory>" in block
    assert "</smith-memory>" in block
    assert "No prior conversation state" in block


def test_block_shows_verbatim_turns_oldest_first_with_timestamps():
    t0 = datetime(2026, 7, 15, 14, 3)
    t1 = t0 + timedelta(minutes=1)
    verbatim = [
        MemoryTurn(role="user", content="Schedule button is broken", created_at=t0),
        MemoryTurn(
            role="assistant",
            content="Found the bug — proposing a fix.",
            created_at=t1,
            intent="FIX",
            pending_fix=True,
        ),
    ]
    block = build_memory_block(verbatim, ["applied change at 12:00: some fix"])
    # Verbatim renders both, oldest first, with role + HH:MM + content.
    assert "user (14:03)" in block
    assert "assistant (14:04)" in block
    # Tags for the assistant turn should include intent + pending_fix.
    idx_asst = block.index("assistant (14:04)")
    tag_slice = block[idx_asst : idx_asst + 200]
    assert "FIX" in tag_slice
    assert "pending_fix" in tag_slice
    # State line appears above the verbatim.
    assert block.index("applied change at 12:00") < idx_asst


def test_block_clips_a_very_long_turn_body():
    """A long turn body must not blow out input tokens — clipped with an
    ellipsis marker."""
    turn = MemoryTurn(role="user", content="x" * 5000, created_at=datetime(2026, 7, 15, 10, 0))
    block = build_memory_block([turn], [])
    assert "…" in block
    # Rough upper bound: header + one clipped line + footer should be well under
    # the raw 5k.
    assert len(block) < 1500


# --------------------------------------------------------------------------- #
# derive_state_lines  — deterministic 'facts on the ground'
# --------------------------------------------------------------------------- #

def _turn(role, content, created_at, **md_flags):
    return MemoryTurn(role=role, content=content, created_at=created_at, **md_flags)


def test_pending_fix_is_the_top_state_line():
    """When the most recent assistant turn has a pending fix that hasn't been
    applied, Smith needs to see it FIRST so he offers Apply rather than
    re-diagnoses."""
    t0 = datetime(2026, 7, 15, 12, 0)
    t1 = t0 + timedelta(hours=4)
    turns = [
        _turn("user", "schedule is broken", t0),
        _turn(
            "assistant",
            "Two fields wrong — proposing fix",
            t1,
            intent="FIX",
            pending_fix=True,
        ),
    ]
    state = derive_state_lines(turns)
    assert state, "state should not be empty"
    assert "pending fix" in state[0].lower()
    assert "16:00" in state[0], "the pending-fix line should carry the time"
    assert "offer to Apply" in state[0]  # Smith-facing instruction


def test_applied_change_shows_first_line_of_the_message():
    t0 = datetime(2026, 7, 15, 9, 0)
    turns = [
        _turn("user", "please fix", t0),
        _turn(
            "assistant",
            "Fixed the Schedule button.\nThis is a second line.",
            t0 + timedelta(minutes=1),
            intent="FIX",
            applied=True,
        ),
    ]
    state = derive_state_lines(turns)
    assert any("applied change" in s for s in state)
    assert any("Fixed the Schedule button" in s for s in state)
    # No second-line noise leaks in.
    assert not any("second line" in s for s in state)


def test_apply_that_left_issues_gets_a_continuation_line():
    """The apply-outcome turn on real applies stores verify.remaining. When
    the LATEST apply had unresolved issues, memory must promote a
    'continue on affirmative reply' hint at the top of state so a follow-up
    like 'yes please' doesn't restart the conversation cold."""
    t0 = datetime(2026, 7, 16, 1, 10)
    turns = [
        _turn("user", "In Add Candidate page, CV upload is failing", t0),
        _turn("assistant", "I found the likely cause and can fix it.",
              t0 + timedelta(seconds=15), intent="FIX", pending_fix=True),
        _turn("user", "[APPLY_FIX]", t0 + timedelta(seconds=30)),
        _turn(
            "assistant",
            "I applied the change, but my re-check still sees an issue (1 remaining). Want me to take another look?",
            t0 + timedelta(minutes=1),
            intent="FIX", applied=True,
        ),
    ]
    # Simulate the apply-turn's verify metadata by overriding on the fixture
    # (in production this comes from normalize_conversation_rows).
    turns[-1].apply_resolved = False
    turns[-1].apply_remaining = 1

    state = derive_state_lines(turns)
    joined = " | ".join(state)
    assert "last apply at 01:11 left 1 issue(s) unresolved" in joined
    assert "CONTINUE investigating the SAME feature" in joined
    assert "yes" in joined  # explicit affirmative trigger


def test_resolved_apply_does_not_emit_continuation_hint():
    """When the apply cleaned up, don't promote a continuation line — just
    the normal 'applied change' summary."""
    t0 = datetime(2026, 7, 16, 1, 10)
    turns = [
        _turn("user", "fix it", t0),
        _turn("assistant", "Applied. All clean.",
              t0 + timedelta(minutes=1), intent="FIX", applied=True),
    ]
    turns[-1].apply_resolved = True
    turns[-1].apply_remaining = 0

    state = derive_state_lines(turns)
    joined = " | ".join(state)
    assert "applied change" in joined
    assert "unresolved" not in joined
    assert "CONTINUE" not in joined


def test_normalize_reads_verify_remaining_from_metadata():
    """normalize_conversation_rows must extract verify.resolved + remaining
    count from Conversation.metadata so derive_state_lines has what it needs."""
    t = datetime(2026, 7, 16, 1, 11)
    rows = [
        {
            "role": "assistant",
            "content": "I applied the change, but 1 issue remains.",
            "created_at": t,
            "metadata": {
                "intent": "FIX",
                "fixApplied": True,
                "verify": {"resolved": False, "remaining": [{"reason": "still-broken"}]},
            },
        },
    ]
    turns = normalize_conversation_rows(rows)
    assert turns[0].applied is True
    assert turns[0].apply_resolved is False
    assert turns[0].apply_remaining == 1


def test_pending_then_applied_shows_only_the_applied_line():
    """If a pending fix was later applied, the pending marker disappears —
    the applied line supersedes it."""
    t0 = datetime(2026, 7, 15, 9, 0)
    turns = [
        _turn("user", "schedule broken", t0),
        _turn(
            "assistant",
            "Proposing fix",
            t0 + timedelta(minutes=1),
            intent="FIX",
            pending_fix=True,
        ),
        _turn("user", "yes fix it", t0 + timedelta(minutes=2)),
        _turn(
            "assistant",
            "Fix applied.",
            t0 + timedelta(minutes=3),
            intent="FIX",
            applied=True,
        ),
    ]
    state = derive_state_lines(turns)
    joined = " | ".join(state).lower()
    assert "applied change" in joined
    assert "pending fix" not in joined


def test_state_falls_back_to_latest_intent_when_nothing_applied():
    t0 = datetime(2026, 7, 15, 9, 0)
    turns = [
        _turn("user", "help", t0),
        _turn("assistant", "asked a clarifying question", t0 + timedelta(minutes=1), intent="FIX"),
    ]
    state = derive_state_lines(turns)
    assert state == ["most recent intent: FIX"]


def test_state_is_capped_at_max_rows():
    from services.smith_memory import _STATE_MAX_ROWS
    turns = []
    for i in range(30):
        t = datetime(2026, 7, 15, 9, i)
        turns.append(_turn("user", "x", t))
        turns.append(_turn(
            "assistant",
            f"applied fix #{i}",
            t + timedelta(seconds=30),
            intent="FIX",
            applied=True,
        ))
    state = derive_state_lines(turns)
    assert len(state) <= _STATE_MAX_ROWS


# --------------------------------------------------------------------------- #
# normalize_conversation_rows  — accepts ORM rows AND dicts
# --------------------------------------------------------------------------- #

def test_normalize_accepts_dicts_and_sorts_oldest_first():
    t0 = datetime(2026, 7, 15, 10, 0)
    t1 = t0 + timedelta(minutes=1)
    rows = [
        # Deliberately newest first — should be sorted to oldest first.
        {"role": "assistant", "content": "hello", "created_at": t1, "metadata": {"intent": "FIX"}},
        {"role": "user",      "content": "hi",    "created_at": t0, "metadata": {}},
    ]
    turns = normalize_conversation_rows(rows)
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[1].role == "assistant"
    assert turns[1].intent == "FIX"


def test_normalize_skips_system_and_unknown_roles():
    t0 = datetime(2026, 7, 15, 10, 0)
    rows = [
        {"role": "system", "content": "x", "created_at": t0, "metadata": {}},
        {"role": "user", "content": "y", "created_at": t0, "metadata": {}},
        {"role": "gremlin", "content": "z", "created_at": t0, "metadata": {}},
    ]
    turns = normalize_conversation_rows(rows)
    assert [t.role for t in turns] == ["user"]


def test_normalize_reads_enum_role_via_value():
    """The Conversation model uses a MessageRole enum whose repr is
    'MessageRole.assistant'. Normalize must unwrap .value."""
    role_enum = SimpleNamespace(value="assistant")
    row = {"role": role_enum, "content": "x", "created_at": datetime(2026,7,15), "metadata": {}}
    turns = normalize_conversation_rows([row])
    assert len(turns) == 1
    assert turns[0].role == "assistant"


def test_normalize_treats_orm_row_and_dict_equivalently():
    t = datetime(2026, 7, 15, 10, 0)
    orm_row = SimpleNamespace(
        role="user", content="hi", created_at=t, metadata_={"intent": "PLAN"},
    )
    dict_row = {"role": "user", "content": "hi", "created_at": t, "metadata": {"intent": "PLAN"}}
    assert normalize_conversation_rows([orm_row])[0].intent == "PLAN"
    assert normalize_conversation_rows([dict_row])[0].intent == "PLAN"


def test_normalize_marks_applied_when_commit_hash_present():
    """A refine turn stores commit_hash but not fixApplied; both should be
    treated as 'applied' state."""
    t = datetime(2026, 7, 15, 10, 0)
    rows = [
        {"role": "assistant", "content": "done", "created_at": t,
         "metadata": {"commit_hash": "abc123"}},
    ]
    turns = normalize_conversation_rows(rows)
    assert turns[0].applied is True


# --------------------------------------------------------------------------- #
# build_smith_memory  — window + state composition
# --------------------------------------------------------------------------- #

def test_build_memory_keeps_only_last_N_verbatim_but_all_for_state():
    t0 = datetime(2026, 7, 15, 9, 0)
    turns = []
    for i in range(10):
        t = t0 + timedelta(minutes=i)
        turns.append(_turn("user", f"u{i}", t))
        turns.append(_turn(
            "assistant",
            f"applied a{i}",
            t + timedelta(seconds=30),
            intent="FIX",
            applied=True,
        ))
    mem = build_smith_memory(turns, verbatim_n=3)
    # Verbatim is bounded to 3 trailing turns.
    assert len(mem.verbatim) == 3
    assert mem.verbatim[-1].content.startswith("applied a9")
    # State sees the full history — should have multiple 'applied change' rows.
    joined = " ".join(mem.state_lines)
    assert joined.count("applied change") >= 3


def test_build_memory_verbatim_zero_is_state_only():
    t0 = datetime(2026, 7, 15, 9, 0)
    turns = [
        _turn("user", "hi", t0),
        _turn("assistant", "applied thing", t0 + timedelta(minutes=1),
              intent="FIX", applied=True),
    ]
    mem = build_smith_memory(turns, verbatim_n=0)
    assert mem.verbatim == []
    assert any("applied change" in s for s in mem.state_lines)


# --------------------------------------------------------------------------- #
# read_smith_memory  — thin DB read; mock the async session
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_read_smith_memory_returns_empty_on_db_failure():
    """A DB error must degrade to an empty SmithMemory — never blow up the
    Smith turn."""
    class _BadSess:
        async def execute(self, *_a, **_kw):
            raise RuntimeError("DB down")
    mem = await read_smith_memory(_BadSess(), uuid.uuid4())
    assert isinstance(mem, SmithMemory)
    assert mem.is_empty()


@pytest.mark.asyncio
async def test_read_smith_memory_builds_from_mocked_query():
    """Wire a fake AsyncSession that returns two turns → normalize + build."""
    t0 = datetime(2026, 7, 15, 12, 0)
    orm_a = SimpleNamespace(
        role=SimpleNamespace(value="user"),
        content="schedule broken",
        created_at=t0,
        metadata_={},
    )
    orm_b = SimpleNamespace(
        role=SimpleNamespace(value="assistant"),
        content="proposing fix",
        created_at=t0 + timedelta(minutes=1),
        metadata_={"intent": "FIX", "pending_fix": {"seam": "workflow_node_config"}},
    )

    class _Result:
        def scalars(self):
            # DB returns newest-first; normalize sorts oldest-first.
            return [orm_b, orm_a]

    class _FakeSess:
        async def execute(self, *_a, **_kw):
            return _Result()

    mem = await read_smith_memory(_FakeSess(), uuid.uuid4())
    assert len(mem.verbatim) == 2
    assert mem.verbatim[0].role == "user"
    assert mem.verbatim[1].role == "assistant"
    assert mem.verbatim[1].pending_fix is True
    # Pending-fix line surfaces in state.
    assert any("pending fix" in s.lower() for s in mem.state_lines)


# --------------------------------------------------------------------------- #
# CTX-1: last-touched tracking + resource-slice injection
# --------------------------------------------------------------------------- #

from services.smith_memory import derive_last_touched, path_to_route


def test_derive_last_touched_none_when_no_edited_paths():
    """No assistant turn ever recorded edited_paths → None; Smith has no
    focal artifact to slice context for."""
    t0 = datetime(2026, 7, 20, 9, 0)
    turns = [
        _turn("user", "hi", t0),
        _turn("assistant", "hello", t0 + timedelta(seconds=1)),
    ]
    assert derive_last_touched(turns) is None


def test_derive_last_touched_reads_most_recent_assistant_with_paths():
    """Walk newest → oldest, return the first assistant turn whose
    edited_paths is non-empty. Route is derived from the first path."""
    t0 = datetime(2026, 7, 20, 9, 0)
    turns = [
        _turn("user", "add save button", t0),
        MemoryTurn(
            role="assistant",
            content="Done.",
            created_at=t0 + timedelta(seconds=30),
            edited_paths=["src/schemas/application-2/new.json"],
        ),
        _turn("user", "button doesn't work", t0 + timedelta(minutes=2)),
    ]
    assert derive_last_touched(turns) == "/application-2/new"


def test_derive_last_touched_prefers_newer_over_older():
    """Two assistant turns both with paths — the NEWER wins."""
    t0 = datetime(2026, 7, 20, 9, 0)
    turns = [
        MemoryTurn(
            role="assistant", content="edit 1",
            created_at=t0,
            edited_paths=["src/schemas/candidates/edit.json"],
        ),
        MemoryTurn(
            role="assistant", content="edit 2",
            created_at=t0 + timedelta(minutes=5),
            edited_paths=["src/schemas/drives/new.json"],
        ),
    ]
    assert derive_last_touched(turns) == "/drives/new"


def test_derive_last_touched_ignores_user_turns():
    """A user turn cannot 'touch' paths — only assistant tool calls do."""
    t0 = datetime(2026, 7, 20, 9, 0)
    user_with_bogus_paths = MemoryTurn(
        role="user", content="", created_at=t0,
        edited_paths=["src/schemas/foo/new.json"],
    )
    turns = [user_with_bogus_paths]
    assert derive_last_touched(turns) is None


def test_path_to_route_strips_src_schemas_and_json_suffix():
    """The path→route heuristic must handle the canonical schema layout."""
    assert path_to_route("src/schemas/candidates/new.json") == "/candidates/new"
    assert path_to_route("src/schemas/dashboard.json") == "/dashboard"
    # Absolute paths still work.
    assert (
        path_to_route("/some/output/dir/src/schemas/pipeline/[driveId].json")
        == "/pipeline/[driveId]"
    )
    # A page.tsx or route.ts also collapses cleanly to its route.
    assert (
        path_to_route("src/app/candidates/new/page.tsx")
        == "/candidates/new"
    )


def test_path_to_route_returns_none_for_unrecognized_shapes():
    """A path we can't map to a route (config file, README, etc.) returns
    None so callers know not to try building a slice for it."""
    assert path_to_route("package.json") is None
    assert path_to_route("src/lib/utils.ts") is None
    assert path_to_route("") is None


def test_normalize_conversation_rows_extracts_edited_paths_from_metadata():
    """The Smith terminal handler persists ``edited_paths`` on the
    assistant Conversation row. normalize_conversation_rows must lift
    them into ``MemoryTurn.edited_paths`` so derive_last_touched works
    on the next turn."""
    t = datetime(2026, 7, 20, 10, 0)
    rows = [
        {
            "role": "assistant",
            "content": "Added save button.",
            "created_at": t,
            "metadata": {
                "intent": "SMITH",
                "edited_paths": ["src/schemas/application-2/new.json"],
                "commit_hash": "abc123",
            },
        },
    ]
    turns = normalize_conversation_rows(rows)
    assert turns[0].edited_paths == ["src/schemas/application-2/new.json"]


def test_normalize_missing_edited_paths_defaults_to_empty_list():
    """Legacy rows without the field — no crash, empty list."""
    t = datetime(2026, 7, 20, 10, 0)
    rows = [{"role": "assistant", "content": "hi", "created_at": t, "metadata": {}}]
    turns = normalize_conversation_rows(rows)
    assert turns[0].edited_paths == []


def test_build_memory_block_appends_resource_slice_section_when_provided():
    """When a resource_slice is passed, it renders as its own section
    inside the memory block so Smith sees ArtifactContext alongside chat
    history."""
    block = build_memory_block(
        [], [],
        resource_slice="<resource-registry>\nEntity: Application\n</resource-registry>",
    )
    assert "## Last-touched context" in block
    assert "Entity: Application" in block


def test_build_memory_block_no_slice_omits_the_section():
    """No slice → no empty header. Smith shouldn't see '## Last-touched
    context' with nothing under it."""
    block = build_memory_block([], [], resource_slice="")
    assert "Last-touched context" not in block


def test_smith_memory_to_prompt_block_carries_resource_slice_through():
    """SmithMemory.resource_slice must reach the rendered block."""
    mem = SmithMemory(
        verbatim=[],
        state_lines=[],
        resource_slice="<resource-registry>\n(slice)\n</resource-registry>",
    )
    block = mem.to_prompt_block()
    assert "(slice)" in block
    assert "## Last-touched context" in block

def test_build_memory_block_authoritative_directive_present_with_blueprint():
    """When a blueprint is supplied, the header must carry the
    'source of truth / reconcile the file to match' directive so Smith
    treats it as authoritative rather than as one context clue among
    many."""
    block = build_memory_block(
        [], [],
        blueprint="# App\n\n## Data Model\nTenant: …\n",
    )
    assert "## App blueprint (authoritative — always current)" in block
    assert "source of truth for this app" in block
    assert "reconcile the file to match" in block
    assert "cite the blueprint section" in block.lower()


def test_build_memory_block_no_directive_when_no_blueprint():
    """No blueprint → no authoritative directive noise. The header + the
    reconciliation instruction only appear alongside the blueprint they
    apply to."""
    block = build_memory_block([], [], blueprint="")
    assert "authoritative — always current" not in block
    assert "reconcile the file to match" not in block


def test_smith_agent_system_prompt_carries_blueprint_directive():
    """The system prompt must tell Smith that the blueprint is his
    primary reference and to consult it FIRST."""
    from agents.smith_agent import build_system_prompt
    sp = build_system_prompt()
    assert "BLUEPRINT" in sp
    assert "primary reference" in sp
    assert "consult it FIRST" in sp or "consult" in sp.lower()


import uuid  # placed at bottom on purpose — the mock-based tests import it
