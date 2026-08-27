"""Smith orchestrator — the outer Actor-Critic loop with the guard
suite as the critic.

Every test injects `smith_fn` + `guard_fn` + `diff_fn` + `commit_fn`
+ `revert_fn` + `recall_fn` fakes so the loop runs synchronously and
never touches the LLM, git, or disk. Coverage: convergence, retry-
until-green, ask_user passthrough, handoff passthrough, no-op,
turns-exhausted rollback, exception rollback."""
from __future__ import annotations

import pytest

from services.guard_result import GuardResult, GuardFailure
from services.smith_orchestrator import run, OrchestratorResult


# =========================================================================
# Fake seams
# =========================================================================

def _fake_recall(_out): return "RECALL: ok"


def _make_smith_fn(scripted: list[dict]):
    """Return a smith_fn that yields scripted[0], scripted[1], … per call."""
    calls: list[dict] = []
    def _fn(**kwargs):
        calls.append(kwargs)
        if not scripted:
            raise AssertionError("smith called more times than scripted")
        return scripted.pop(0)
    _fn.calls = calls  # type: ignore[attr-defined]
    return _fn


_EMPTY_BASELINE = GuardResult(green=True, failures=[], raw_lines=[])


def _make_guard_fn(verdicts: list[GuardResult]):
    """Yield verdicts[0], verdicts[1], … per call; asserts on overflow.

    The orchestrator calls guards ONCE at start (baseline snapshot) then
    once per turn that produced edits. This helper transparently prepends
    an all-green baseline so callers only script the per-turn verdicts,
    matching how the tests were written before baseline capture existed."""
    calls: list[str] = []
    queue = [_EMPTY_BASELINE, *verdicts]
    def _fn(output_dir: str):
        calls.append(output_dir)
        if not queue:
            raise AssertionError("guards called more times than scripted")
        return queue.pop(0)
    _fn.calls = calls  # type: ignore[attr-defined]
    return _fn


def _make_recorder():
    """A recorder for commit/revert/diff calls."""
    events: list[tuple[str, tuple, dict]] = []
    def _mk(name, retval):
        def _fn(*a, **kw):
            events.append((name, a, kw))
            return retval
        return _fn
    return events, _mk


# =========================================================================
# Terminal: ask_user
# =========================================================================

def test_ask_user_terminates_without_touching_guards():
    """When Smith's first turn is `ask_user`, the orchestrator returns
    'asked' immediately — no guard run, no edits, no commit."""
    smith = _make_smith_fn([
        {"question": "which page?", "answer": None, "edited_paths": [], "trace": []},
    ])
    guards = _make_guard_fn([])  # would raise if called

    r = run("ask", "/tmp/app",
            smith_fn=smith, guard_fn=guards, recall_fn=_fake_recall)
    assert r.status == "asked"
    assert r.question == "which page?"
    assert r.applied_paths == []
    assert r.turns == 1
    # Baseline snapshot always runs first, even for ask_user turns.
    assert guards.calls == ["/tmp/app"]


# =========================================================================
# Terminal: handoff_to_pipeline
# =========================================================================

def test_handoff_terminates_without_guards():
    smith = _make_smith_fn([
        {"handoff": {"kind": "planner", "reason": "big change"},
         "answer": "handing off to planner", "edited_paths": [], "trace": []},
    ])
    guards = _make_guard_fn([])
    r = run("plan a whole new thing", "/tmp/app",
            smith_fn=smith, guard_fn=guards, recall_fn=_fake_recall)
    assert r.status == "handoff"
    assert r.handoff == {"kind": "planner", "reason": "big change"}


# =========================================================================
# No-op — no edits, no ask, no handoff → informational answer
# =========================================================================

def test_no_op_returns_informational_answer():
    smith = _make_smith_fn([
        {"answer": "here's how the app works", "edited_paths": [], "trace": []},
    ])
    guards = _make_guard_fn([])
    r = run("how does it work?", "/tmp/app",
            smith_fn=smith, guard_fn=guards, recall_fn=_fake_recall)
    assert r.status == "no_op"
    assert "how the app works" in r.answer


# =========================================================================
# Convergence on turn 1
# =========================================================================

def test_converges_when_first_edit_passes_guards():
    """Happy path: one Smith turn produces edits, guards are green,
    orchestrator commits + answers from diff."""
    smith = _make_smith_fn([
        {"answer": "changed to FileUpload",
         "edited_paths": ["src/schemas/candidates/new.json"], "trace": []},
    ])
    guards = _make_guard_fn([GuardResult(green=True, failures=[], raw_lines=[])])
    events, mk = _make_recorder()
    r = run("change field to file upload", "/tmp/app",
            smith_fn=smith, guard_fn=guards,
            diff_fn=mk("diff", "type: Select → FileUpload"),
            commit_fn=mk("commit", "abc12345"),
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    assert r.status == "resolved"
    assert r.turns == 1
    assert r.applied_paths == ["src/schemas/candidates/new.json"]
    assert r.commit == "abc12345"
    # Answer text derives from the diff — NOT Smith's own summary.
    assert "type: Select → FileUpload" in r.answer
    # Commit was called, revert was not.
    assert any(e[0] == "commit" for e in events)
    assert not any(e[0] == "revert" for e in events)


# =========================================================================
# Retry: red guard on turn 1, green on turn 2
# =========================================================================

def test_retries_on_red_guards_and_succeeds_on_turn_2():
    smith = _make_smith_fn([
        # Turn 1: edit page — but this creates a workflow mismatch.
        {"answer": "changed to FileUpload",
         "edited_paths": ["src/schemas/candidates/new.json"], "trace": []},
        # Turn 2: (fed corrective context) — edit the workflow too.
        {"answer": "added input to workflow",
         "edited_paths": ["workflows/process_cv.json"], "trace": []},
    ])
    guards = _make_guard_fn([
        GuardResult(
            green=False,
            failures=[GuardFailure(guard="workflow_mutation_guard",
                                    kind="warning",
                                    message="1 mutation value still needs a trigger input")],
            raw_lines=[],
        ),
        GuardResult(green=True, failures=[], raw_lines=[]),
    ])
    events, mk = _make_recorder()
    r = run("change field to FileUpload", "/tmp/app",
            smith_fn=smith, guard_fn=guards,
            diff_fn=mk("diff", "field type changed + workflow input added"),
            commit_fn=mk("commit", "sha22222"),
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    assert r.status == "resolved"
    assert r.turns == 2
    assert set(r.applied_paths) == {
        "src/schemas/candidates/new.json",
        "workflows/process_cv.json",
    }
    assert r.commit == "sha22222"
    # Both smith turns fired; second call must have contained corrective context.
    assert len(smith.calls) == 2
    assert "CORRECTIVE CONTEXT" in smith.calls[1]["user_message"]
    assert "workflow_mutation_guard" in smith.calls[1]["user_message"]


# =========================================================================
# Turns exhausted → rollback + honest failure
# =========================================================================

def test_max_turns_exhausted_reverts_and_reports_honestly():
    """Every turn produces edits, guards never green. Orchestrator
    hits the cap, reverts, returns 'rolled_back' — NOT 'resolved'."""
    n_turns = 3
    smith = _make_smith_fn([
        {"answer": f"attempt {i}", "edited_paths": [f"f{i}.json"], "trace": []}
        for i in range(n_turns)
    ])
    guards = _make_guard_fn([
        GuardResult(green=False, failures=[
            GuardFailure(guard="never_happy", kind="warning",
                         message=f"round {i}"),
        ], raw_lines=[])
        for i in range(n_turns)
    ])
    events, mk = _make_recorder()
    r = run("try to fix", "/tmp/app",
            max_outer_turns=n_turns,
            smith_fn=smith, guard_fn=guards,
            diff_fn=mk("diff", ""),
            commit_fn=mk("commit", "should-not-fire"),
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    assert r.status == "rolled_back"
    assert "reverted" in r.answer.lower() or "revert" in r.answer.lower()
    assert "never_happy" in r.answer  # last guard's failures surfaced
    # Revert fired, commit did NOT.
    revert_calls = [e for e in events if e[0] == "revert"]
    commit_calls = [e for e in events if e[0] == "commit"]
    assert len(revert_calls) == 1
    assert len(commit_calls) == 0
    # Every path Smith touched shows up in the revert.
    reverted_paths = revert_calls[0][1][1]
    assert set(reverted_paths) == {"f0.json", "f1.json", "f2.json"}


# =========================================================================
# Answer synthesis — never parrots Smith's prose
# =========================================================================

def test_relevance_gate_refuses_when_wrong_file_touched():
    """The user asks about the Add Candidate CV field; Smith edits an
    unrelated file. Guards are green but the relevance gate refuses
    to mark resolved — this is the exact cheapest-edit-wins bug we saw
    on the live run where Smith reformatted labels instead of changing
    the Select to a FileUpload."""
    smith = _make_smith_fn([
        {"answer": "did some cosmetic reformatting",
         "edited_paths": ["src/schemas/other/settings.json"],
         "understanding": {
             "screen": "Add Candidate",
             "element_label": "Upload CV",
             "current_behavior": "Select",
             "desired_behavior": "FileUpload",
             "target_file": "src/schemas/candidates/new.json",
         },
         "trace": []},
        # Second turn — Smith gives up (avoids infinite loop in test).
        {"question": "which page again?", "edited_paths": [], "trace": []},
    ])
    guards = _make_guard_fn([
        GuardResult(green=True, failures=[], raw_lines=[]),
    ])
    events, mk = _make_recorder()
    r = run("In Add Candidate, upload CV is the drop down", "/tmp/app",
            smith_fn=smith, guard_fn=guards,
            diff_fn=mk("diff", "settings.json | 5 +--"),
            commit_fn=mk("commit", "abc"),
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    assert r.status == "asked"  # Smith bailed on turn 2 rather than commit the miss
    # Critical: NO commit happened despite guards being green.
    commit_calls = [e for e in events if e[0] == "commit"]
    assert commit_calls == []


def test_relevance_gate_refuses_when_element_label_missing_from_diff():
    """Smith edits the RIGHT file but doesn't touch the specific
    element the user named — only reformats other fields in the same
    file. Diff doesn't mention the element_label → gate refuses."""
    smith = _make_smith_fn([
        {"answer": "reformatted labels",
         "edited_paths": ["src/schemas/candidates/new.json"],
         "understanding": {
             "screen": "Add Candidate",
             "element_label": "Upload CV",
             "current_behavior": "Select",
             "desired_behavior": "FileUpload",
             "target_file": "src/schemas/candidates/new.json",
         },
         "trace": []},
        {"question": "which field?", "edited_paths": [], "trace": []},
    ])
    guards = _make_guard_fn([
        GuardResult(green=True, failures=[], raw_lines=[]),
    ])
    events, mk = _make_recorder()
    r = run("In Add Candidate, upload CV is the drop down", "/tmp/app",
            smith_fn=smith, guard_fn=guards,
            # Diff exists but doesn't mention "Upload CV" — cosmetic edits only.
            diff_fn=mk("diff",
                       'changed label "First Name" → "First Name *"\n'
                       'changed label "Email" → "Email address"'),
            commit_fn=mk("commit", "abc"),
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    assert r.status == "asked"
    assert not [e for e in events if e[0] == "commit"]


def test_relevance_gate_passes_when_file_and_element_both_present():
    """The happy path: Smith touches the right file AND the diff
    mentions the element by label."""
    smith = _make_smith_fn([
        {"answer": "changed Select to FileUpload on Upload CV",
         "edited_paths": ["src/schemas/candidates/new.json"],
         "understanding": {
             "screen": "Add Candidate",
             "element_label": "Upload CV",
             "current_behavior": "Select",
             "desired_behavior": "FileUpload",
             "target_file": "src/schemas/candidates/new.json",
         },
         "trace": []},
    ])
    guards = _make_guard_fn([
        GuardResult(green=True, failures=[], raw_lines=[]),
    ])
    events, mk = _make_recorder()
    r = run("upload CV should be a file field", "/tmp/app",
            smith_fn=smith, guard_fn=guards,
            diff_fn=mk("diff",
                       '- "type": "Select", "label": "Upload CV", '
                       '"optionsFrom": {...}\n'
                       '+ "type": "FileUpload", "label": "Upload CV", '
                       '"accept": "application/pdf"'),
            commit_fn=mk("commit", "sha"),
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    assert r.status == "resolved"
    assert [e[0] for e in events if e[0] == "commit"] == ["commit"]


def test_relevance_gate_skipped_when_no_understanding():
    """Backwards compat: turns that don't emit understand_ask (e.g. the
    old code paths, or legitimate no-op answers) still work. The gate
    only fires when there's both an understanding and a diff."""
    smith = _make_smith_fn([
        {"answer": "just answering", "edited_paths": ["a.json"],
         "trace": []},  # no understanding key
    ])
    guards = _make_guard_fn([
        GuardResult(green=True, failures=[], raw_lines=[]),
    ])
    events, mk = _make_recorder()
    r = run("hi", "/tmp/app",
            smith_fn=smith, guard_fn=guards,
            diff_fn=mk("diff", "..."),
            commit_fn=mk("commit", "sha"),
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    assert r.status == "resolved"


def test_answer_comes_from_diff_not_smith_prose():
    """Even if Smith writes a plausible-sounding lie, the orchestrator's
    answer is derived from the git diff — the ground truth. This is
    the whole 'believes he did it' defense."""
    smith = _make_smith_fn([
        {"answer": "Done! Changed everything to FileUpload!",  # ← plausible lie
         "edited_paths": ["src/schemas/candidates/new.json"], "trace": []},
    ])
    guards = _make_guard_fn([GuardResult(green=True, failures=[], raw_lines=[])])
    events, mk = _make_recorder()

    r = run("change field type", "/tmp/app",
            smith_fn=smith, guard_fn=guards,
            diff_fn=mk("diff", "only label changed: 'Latest CV' → 'Upload CV'"),
            commit_fn=mk("commit", "sha"),
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    # The orchestrator answer names WHAT ACTUALLY CHANGED.
    assert "only label changed" in r.answer
    # It does NOT echo Smith's boastful summary.
    assert "Done! Changed everything to FileUpload" not in r.answer


# =========================================================================
# Exception safety — mid-turn crash reverts + returns honest error
# =========================================================================

def test_orchestrator_never_raises_on_smith_exception():
    """A raise inside smith_fn must not escape the orchestrator; it's
    converted to a rolled-back result with the exception in the message."""
    def _blowup(**kwargs):
        raise RuntimeError("simulated LLM crash")
    events, mk = _make_recorder()
    r = run("hi", "/tmp/app",
            smith_fn=_blowup,
            guard_fn=_make_guard_fn([]),
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    assert r.status == "rolled_back"
    assert "simulated LLM crash" in r.answer


def test_orchestrator_never_raises_on_guard_exception():
    def _bad_guards(_out):
        raise RuntimeError("guard suite crashed")
    smith = _make_smith_fn([
        {"answer": "done", "edited_paths": ["a.json"], "trace": []},
    ])
    events, mk = _make_recorder()
    r = run("hi", "/tmp/app",
            smith_fn=smith, guard_fn=_bad_guards,
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    assert r.status == "rolled_back"
    assert "guard suite crashed" in r.answer


# =========================================================================
# Recall injection
# =========================================================================

def test_recall_block_passed_to_smith():
    """The enriched recall must reach Smith on every turn — no recall
    means no component catalog, means Smith picks the shortest edit."""
    smith = _make_smith_fn([
        {"answer": "ok", "edited_paths": ["x.json"], "trace": []},
    ])
    guards = _make_guard_fn([GuardResult(green=True, failures=[], raw_lines=[])])
    events, mk = _make_recorder()
    def _my_recall(_out):
        return "MY-CUSTOM-RECALL"
    run("hi", "/tmp/app",
        smith_fn=smith, guard_fn=guards,
        diff_fn=mk("diff", "x"), commit_fn=mk("commit", "sha"),
        revert_fn=mk("revert", True),
        recall_fn=_my_recall)
    assert smith.calls[0]["recall_block"] == "MY-CUSTOM-RECALL"


# =========================================================================
# Multiple edits accumulate across turns
# =========================================================================

def test_applied_paths_accumulate_across_retries():
    smith = _make_smith_fn([
        {"answer": "edit 1", "edited_paths": ["a.json"], "trace": []},
        {"answer": "edit 2", "edited_paths": ["b.json"], "trace": []},
        {"answer": "edit 3", "edited_paths": ["c.json"], "trace": []},
    ])
    guards = _make_guard_fn([
        GuardResult(green=False, failures=[GuardFailure("g", "warning", "m")], raw_lines=[]),
        GuardResult(green=False, failures=[GuardFailure("g", "warning", "m")], raw_lines=[]),
        GuardResult(green=True,  failures=[], raw_lines=[]),
    ])
    events, mk = _make_recorder()
    r = run("multi", "/tmp/app",
            smith_fn=smith, guard_fn=guards,
            diff_fn=mk("diff", "all three edits"),
            commit_fn=mk("commit", "abc"),
            revert_fn=mk("revert", True),
            recall_fn=_fake_recall)
    assert r.status == "resolved"
    assert set(r.applied_paths) == {"a.json", "b.json", "c.json"}
    assert r.turns == 3


# =========================================================================
# Result.to_dict — the router serializes to send SSE / persist
# =========================================================================

def test_result_to_dict_serializable():
    r = OrchestratorResult(status="no_op", answer="nothing changed")
    import json
    d = r.to_dict()
    # Should round-trip through JSON without exceptions.
    json.dumps(d)
    assert d["status"] == "no_op"
