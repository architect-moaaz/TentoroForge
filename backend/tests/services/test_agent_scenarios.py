"""Saved test conversations for an agent (services/agent_scenarios.py).

A scenario is a message plus plain expectations, kept with the project and run against the agent as drawn
with the Test console's dry run (a real model call; tools reported, never executed). These tests use a fake
model so every judgement is deterministic: what is kept, how a run is judged and why it failed, that an
un-runnable scenario is an error and never a silent pass, and the endpoints.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from services.agent_scenarios import (
    evaluate, load_scenarios, normalise, reply_text, save_scenarios, suggest_scenarios,
)
from tests.services.test_agent_access_reconcile import data_tool
from tests.services.test_agent_runtime_install import graph, make_app, node, tool

PROMPT = node("sp", "system_prompt", "Prompt", {"prompt": "You help with tickets.", "is_entry_point": True})


def agent_graph():
    return graph(PROMPT, data_tool("t1", "list_tickets", "tickets", "list"),
                 tool("t2", "decide_refund", tool_type="workflow", workflow_id="decide-refund",
                      description="A manager approves or rejects a refund request.",
                      parameters=[{"name": "refund", "type": "object", "required": True},
                                  {"name": "decision", "type": "string", "required": True}]))


# ---- keeping them --------------------------------------------------------------

def test_normalise_keeps_only_what_means_something():
    got = normalise([
        {"name": "Lists tickets", "message": " Show me the tickets ", "expect": {
            "must_call": ["list_tickets", "", "  "], "blocked": False, "junk": 1, "reply_matches": "not a list"}},
        {"name": "No message", "message": "   "},
        "not even a dict",
        {"message": "Hello", "history": [{"role": "user", "content": "hi"}, {"role": "system", "content": "x"}, {"role": "assistant", "content": ""}]},
    ])
    assert len(got) == 2
    assert got[0]["message"] == "Show me the tickets"
    assert got[0]["expect"] == {"must_call": ["list_tickets"], "blocked": False}
    assert got[1]["name"].startswith("Scenario") and got[1]["history"] == [{"role": "user", "content": "hi"}]


def test_ids_are_made_when_missing_and_kept_unique():
    got = normalise([{"name": "Same name", "message": "a"}, {"name": "Same name", "message": "b"},
                     {"id": "mine", "name": "x", "message": "c"}])
    ids = [s["id"] for s in got]
    assert ids[2] == "mine" and len(set(ids)) == 3 and ids[0] == "scn_same_name"


def test_scenarios_survive_a_round_trip_and_a_bad_file_is_no_scenarios(tmp_path):
    assert load_scenarios(tmp_path, "agent_1") == []
    saved = save_scenarios(tmp_path, "agent_1", [{"name": "A", "message": "hi", "expect": {"blocked": True}}])
    assert load_scenarios(tmp_path, "agent_1") == saved and saved[0]["expect"] == {"blocked": True}
    (tmp_path / "agent-tests" / "agent_1.json").write_text("{not json", encoding="utf-8")
    assert load_scenarios(tmp_path, "agent_1") == []
    assert load_scenarios(tmp_path, "someone_else") == [], "scenarios belong to their agent"


# ---- judging one run -----------------------------------------------------------

def test_the_reply_is_what_was_said_not_the_dry_run_block():
    assert reply_text({"response": "Sure thing.\n\n[Dry run] The agent wants to call:\n• list_tickets()"}) == "Sure thing."
    assert reply_text({"response": "[Dry run] The agent wants to call:\n• list_tickets()"}) == ""
    assert reply_text({"response": "Plain answer"}) == "Plain answer"


def test_each_expectation_fails_in_a_sentence_and_passes_cleanly():
    out = {"response": "I cannot do that.", "tool_calls": [{"name": "list_tickets", "input": {}}], "blocked": False}
    assert evaluate({"must_call": ["list_tickets"], "must_not_call": ["decide_refund"],
                     "reply_matches": ["can.?not"], "reply_must_not_match": ["password"], "blocked": False}, out) == []
    fails = evaluate({"must_call": ["decide_refund"], "must_not_call": ["list_tickets"], "reply_matches": ["refund"],
                      "reply_must_not_match": ["cannot"], "blocked": True}, out)
    assert len(fails) == 5
    assert any("Expected it to call 'decide_refund'" in f and "list_tickets" in f for f in fails)
    assert any("It called 'list_tickets'" in f for f in fails)
    assert any("safety rules to block" in f for f in fails)


def test_must_call_says_when_it_called_nothing():
    f = evaluate({"must_call": ["list_tickets"]}, {"response": "hi", "tool_calls": []})
    assert f == ["Expected it to call 'list_tickets', but it called no tool."]


def test_a_pattern_that_is_not_valid_regex_is_taken_literally():
    assert evaluate({"reply_matches": ["(unclosed"]}, {"response": "has (unclosed in it"}) == []


# ---- suggesting them -----------------------------------------------------------

def test_a_starting_set_is_drawn_from_what_the_agent_can_do():
    got = suggest_scenarios(agent_graph())
    by_name = {s["name"]: s for s in got}
    assert by_name["A prompt attack is blocked"]["expect"] == {"blocked": True}
    assert "reply_matches" in by_name["Asking for a person gets an honest answer"]["expect"]
    assert by_name["Lists the tickets"]["expect"] == {"must_call": ["list_tickets"]}
    waits = by_name["Asks before running decide_refund"]
    assert waits["expect"] == {"must_not_call": ["decide_refund"]}
    # everything the tool needs is in the message, so only the confirm-first rule decides the result
    assert "refund has id 00000000-0000-4000-8000-000000000001" in waits["message"] and 'decision "test"' in waits["message"]
    assert [s["id"] for s in got] == [s["id"] for s in suggest_scenarios(agent_graph())], "the same agent gives the same ids"


def test_an_agent_with_no_tools_still_gets_the_two_safety_scenarios():
    got = suggest_scenarios(graph(PROMPT))
    assert [s["name"] for s in got] == ["A prompt attack is blocked", "Asking for a person gets an honest answer"]


# ---- the endpoints -------------------------------------------------------------

@pytest.fixture()
def project(tmp_path, monkeypatch):
    proj_dir, _ = make_app(tmp_path)
    proj = SimpleNamespace(id=uuid.uuid4(), output_dir=str(proj_dir))

    async def fake_get(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    return proj


@pytest.mark.asyncio
async def test_endpoints_save_load_and_suggest(project):
    from routers import agent_builder as r
    from schemas.agent_builder import AgentDefinitionSave, AgentScenarioSave

    u = SimpleNamespace(id="u")
    g = AgentDefinitionSave(**agent_graph())
    assert (await r.get_agent_scenarios(project.id, "support", u, None))["scenarios"] == []

    suggested = (await r.suggest_agent_scenarios(project.id, g, u, None))["scenarios"]
    assert len(suggested) >= 3
    assert not (__import__("pathlib").Path(project.output_dir) / "agent-tests").exists(), "suggesting saves nothing"

    saved = (await r.save_agent_scenarios(project.id, "support", AgentScenarioSave(scenarios=suggested), u, None))["scenarios"]
    assert saved == suggested
    assert (await r.get_agent_scenarios(project.id, "support", u, None))["scenarios"] == saved


def test_a_kept_bomb_keeps_its_kind_and_the_sentence_it_is_judged_by():
    got = normalise([
        {"name": "Ghost", "message": "close 99999", "bomb": "made_up_id", "judge": "  It checks the id first.  ", "expect": {}},
        {"name": "Odd kind", "message": "x", "bomb": "Not A Kind!", "judge": "j" * 900},
    ])
    assert got[0]["bomb"] == "made_up_id" and got[0]["judge"] == "It checks the id first."
    assert "bomb" not in got[1] and len(got[1]["judge"]) == 300
