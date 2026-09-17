"""The field seams are writes, and the loop has to know it.

``_MUTATING_TOOLS`` is the one list that decides three things about a tool:
that it may not run before ``understand_ask``, that ``answer`` may not follow
it without a verify, and that a mutation ask is not answerable with "Done!"
when no tool in the list was called. ``add_field`` was in it from the first
version. ``rename_field``, ``remove_field`` and ``edit_field`` were not —
though all three reach ``services/smith/field_change.py`` and rewrite the
Blueprint and the projected tree, and what they write is LARGER than the
add's: a rename moves every reference to the name, a removal deletes the
column, its relationships, its controls and its workflow steps along with the
rows' values. So the three changes that most needed the gates were the three
without them.

REGISTERING THEM IS HALF THE CHANGE. ``remove_field`` and ``edit_field``
already answer an unconfirmed call with ``needs_confirmation``, and a tool
that asked a question wrote nothing — so the verify-before-answer gate,
reading only the tool's NAME, refused the answer that carries the question.
The turn then died at the iteration cap and the user never saw the prompt,
which is S24-8's failure again from the other side: the permission could not
be granted because it could not be asked for. The gate now reads the
structural ``needs_confirmation`` record the loop already keeps, and the
answer that stands in for a write must carry OUR marker sentence — the same
string the next turn matches to recognise a "yes".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents import smith_agent
from services import smith_tools
from services.confirmation_gate import (CONFIRMATION_PROMPT_MARKER,
                                        needs_confirmation_result)

FIELD_SEAMS = ("rename_field", "remove_field", "edit_field")


def _canned(*steps):
    def _fn(system_prompt, messages, tool_catalog):
        for step in steps:
            yield step
    return _fn


def _out(tmp_path: Path) -> str:
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({
        "entities": [], "relationships": [], "roles": [], "interactions": [],
    }))
    return str(tmp_path)


def _understanding(verb: str = "remove_field") -> dict:
    return {"tool": "understand_ask", "args": {
        "verb": verb, "entity": "Nurse", "field": "department",
        "new_value": "team", "screen": "/nurses", "element_label": "department",
        "current_behavior": "nurses have a department",
        "desired_behavior": "they do not", "target_file": "/nurses"}}


def _asks() -> dict:
    return needs_confirmation_result(
        "field", "Nurse.department",
        dependents=["the column and its data are dropped"])


@pytest.fixture()
def asking_tool(monkeypatch):
    """`remove_field` as the gate sees it: a question on the first call, a
    write on the confirmed one. Substituted so the loop is exercised without
    a Blueprint on disk — what is under test is the registration, not the seam."""
    calls: list[dict] = []

    def _stub(output_dir, args):
        calls.append(dict(args))
        if args.get("_confirmed"):
            return {"applied": True, "edited_paths": ["src/db/schema/nurse.ts"],
                    "diff_summary": "Nurse.department is gone"}
        return _asks()

    monkeypatch.setitem(smith_tools.READONLY_HANDLERS, "remove_field", _stub)
    return calls


# --------------------------------------------------------------------------- #
# The registration itself
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("tool", FIELD_SEAMS)
def test_every_field_seam_is_a_mutating_tool(tool):
    """A handler that writes the Blueprint and is not in this set is a write
    the loop cannot see."""
    assert tool in smith_agent._MUTATING_TOOLS
    assert tool in smith_tools.READONLY_HANDLERS


def test_the_set_matches_what_the_field_module_can_do():
    """`field_change.run` dispatches four verbs. Three of them are named by a
    tool, and every one of those is registered — so the list cannot drift
    away from the module again without this failing."""
    from services.smith import field_change

    assert {"add_field", *FIELD_SEAMS} <= smith_agent._MUTATING_TOOLS
    assert {"add_field", "rename_field", "remove_field"} <= set(field_change.__all__)


@pytest.mark.parametrize("tool", FIELD_SEAMS)
def test_a_field_seam_cannot_run_before_the_ask_is_understood(tmp_path, tool):
    out = _out(tmp_path)
    result = smith_agent.run_smith_agent(
        "rename the department field to team", out, recall_block="", memory_block="",
        query_fn=_canned(
            {"tool": tool, "args": {"entity": "Nurse", "field": "department",
                                    "new_value": "team", "new_name": "team"}},
            {"tool": "answer", "args": {"text": "Renamed it."}},
        ),
    )
    blocked = [t for t in result["trace"]
               if t["tool"] == tool and "mutation blocked" in (t.get("result_summary") or "")]
    assert len(blocked) == 1
    assert result["answer"] is None


def test_a_field_write_cannot_be_claimed_without_a_verify(tmp_path, asking_tool):
    out = _out(tmp_path)
    result = smith_agent.run_smith_agent(
        "yes", out, recall_block="", memory_block="",
        prior_messages=[{"role": "assistant", "content": _asks()["summary"]}],
        pending_confirmation={"tool": "remove_field", "kind": "field",
                              "target": "Nurse.department", "cascade": False},
        query_fn=_canned(
            _understanding(),
            {"tool": "remove_field", "args": {"entity": "Nurse", "field": "department",
                                              "_confirmed": True}},
            {"tool": "answer", "args": {"text": "Done — the column is gone."}},
            {"tool": "run_guards", "args": {}},
            {"tool": "answer", "args": {"text": "Removed Nurse.department."}},
        ),
    )
    refused = [t for t in result["trace"]
               if t["tool"] == "answer" and "unverified edits" in (t.get("result_summary") or "")]
    assert len(refused) == 1 and "remove_field" in refused[0]["result_summary"]
    assert result["answer"] == "Removed Nurse.department."


# --------------------------------------------------------------------------- #
# Registering them must not make the confirmation ungrantable
# --------------------------------------------------------------------------- #

def test_the_question_a_seam_asks_reaches_the_user(tmp_path, asking_tool):
    """The turn that asks writes nothing, so there is nothing to verify and
    the answer carrying the question must be allowed through."""
    out = _out(tmp_path)
    result = smith_agent.run_smith_agent(
        "remove the department field from nurses", out, recall_block="", memory_block="",
        query_fn=_canned(
            _understanding(),
            {"tool": "remove_field", "args": {"entity": "Nurse", "field": "department"}},
            {"tool": "answer", "args": {"text": _asks()["summary"]}},
        ),
    )
    assert CONFIRMATION_PROMPT_MARKER in (result["answer"] or "")
    assert result["question"] is None
    assert not any("answer refused" in (t.get("result_summary") or "")
                   for t in result["trace"])
    # And the server records what it asked, so the next turn's "yes" has
    # something to attach to.
    assert result["pending_confirmation"] == {
        "tool": "remove_field", "kind": "field",
        "target": "Nurse.department", "cascade": False}


def test_a_turn_that_only_asked_cannot_report_it_as_done(tmp_path, asking_tool):
    """Skipping the verify gate for a question would otherwise hand back the
    fabricated "Done!" it exists to stop — the column is still there."""
    out = _out(tmp_path)
    result = smith_agent.run_smith_agent(
        "remove the department field from nurses", out, recall_block="", memory_block="",
        query_fn=_canned(
            _understanding(),
            {"tool": "remove_field", "args": {"entity": "Nurse", "field": "department"}},
            {"tool": "answer", "args": {"text": "Done — removed the Department field!"}},
            {"tool": "answer", "args": {"text": _asks()["summary"]}},
        ),
    )
    refused = [t for t in result["trace"]
               if t["tool"] == "answer"
               and "unrelayed confirmation" in (t.get("result_summary") or "")]
    assert len(refused) == 1 and "Nurse.department" in refused[0]["result_summary"]
    assert CONFIRMATION_PROMPT_MARKER in (result["answer"] or "")


def test_a_removal_is_granted_end_to_end(tmp_path, asking_tool):
    """Second turn: the server has its own record of the question and this
    message reads as a yes, so `_confirmed` survives and the seam writes."""
    out = _out(tmp_path)
    result = smith_agent.run_smith_agent(
        "yes", out, recall_block="", memory_block="",
        prior_messages=[{"role": "assistant", "content": _asks()["summary"]}],
        pending_confirmation={"tool": "remove_field", "kind": "field",
                              "target": "Nurse.department", "cascade": False},
        query_fn=_canned(
            _understanding(),
            {"tool": "remove_field", "args": {"entity": "Nurse", "field": "department",
                                              "_confirmed": True}},
            {"tool": "run_guards", "args": {}},
            {"tool": "answer", "args": {"text": "Removed Nurse.department."}},
        ),
    )
    assert asking_tool[-1].get("_confirmed") is True
    assert result["answer"] == "Removed Nurse.department."
    assert result["edited_paths"] == ["src/db/schema/nurse.ts"]


def test_the_model_cannot_grant_itself_the_removal(tmp_path, asking_tool):
    """`_confirmed` is an ordinary tool argument, so on its own it is the
    model's own claim. With no record of a question and no yes from the user,
    it is stripped and the tool asks — being in `_MUTATING_TOOLS` is what
    puts these three under that check."""
    out = _out(tmp_path)
    result = smith_agent.run_smith_agent(
        "remove the department field from nurses", out, recall_block="", memory_block="",
        query_fn=_canned(
            _understanding(),
            {"tool": "remove_field", "args": {"entity": "Nurse", "field": "department",
                                              "_confirmed": True}},
            {"tool": "answer", "args": {"text": _asks()["summary"]}},
        ),
    )
    assert asking_tool == [{"entity": "Nurse", "field": "department"}]
    assert CONFIRMATION_PROMPT_MARKER in (result["answer"] or "")


def test_a_declined_removal_asks_again_rather_than_applying(tmp_path, asking_tool):
    out = _out(tmp_path)
    result = smith_agent.run_smith_agent(
        "no, leave it", out, recall_block="", memory_block="",
        prior_messages=[{"role": "assistant", "content": _asks()["summary"]}],
        pending_confirmation={"tool": "remove_field", "kind": "field",
                              "target": "Nurse.department", "cascade": False},
        query_fn=_canned(
            _understanding(),
            {"tool": "remove_field", "args": {"entity": "Nurse", "field": "department",
                                              "_confirmed": True}},
            {"tool": "answer", "args": {"text": _asks()["summary"]}},
        ),
    )
    assert all(not c.get("_confirmed") for c in asking_tool)
    assert result["edited_paths"] == []


# --------------------------------------------------------------------------- #
# The helpers, directly
# --------------------------------------------------------------------------- #

def test_a_question_is_not_an_edit_to_verify():
    fn = smith_agent._edits_without_matching_verify
    assert fn([{"tool": "remove_field", "needs_confirmation": {"kind": "field"}}]) == []
    # The confirmed call right after it IS one.
    assert fn([
        {"tool": "remove_field", "needs_confirmation": {"kind": "field"}},
        {"tool": "remove_field"},
    ]) == ["remove_field"]
    # A write elsewhere in the turn still gates, question or no question.
    assert fn([
        {"tool": "rename_field"},
        {"tool": "remove_field", "needs_confirmation": {"kind": "field"}},
    ]) == ["rename_field"]


def test_the_standing_question_is_the_last_mutation_not_the_last_entry():
    fn = smith_agent._unrelayed_confirmation
    assert fn([]) is None
    assert fn([{"tool": "read_page"}]) is None
    assert fn([{"tool": "remove_field", "needs_confirmation": {"kind": "field",
                                                               "target": "Nurse.department"}}]) == {
        "tool": "remove_field", "kind": "field", "target": "Nurse.department"}
    # Asked, then applied: nothing is outstanding, so the answer about the
    # change that landed is not held to the marker.
    assert fn([
        {"tool": "remove_field", "needs_confirmation": {"kind": "field"}},
        {"tool": "remove_field"},
        {"tool": "run_guards"},
    ]) is None
    # A call the guards refused never asked anything.
    assert fn([{"tool": "remove_field", "ran": False,
                "needs_confirmation": {"kind": "field"}}]) is None
