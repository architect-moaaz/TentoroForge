"""Chats recorded in Watch live, kept with their details and sent to Find problems and the fixer (services/agent_recording.py).

Pinned: what comes from the page is cut down and made safe (unfinished chats, chats with another assistant and repeats are left
out, big tool data is cut, at most one send's worth is kept); what went wrong in a chat is worked out from what was recorded;
each chat becomes a saved test that knows what really happened; sending twice adds nothing twice and never touches the builder's
own tests; and the fixer is shown the real chats (what the person wrote, what the tools did, what was wrong) and its fixes are kept
only when they can really be applied, naming the saved tests they are for.
"""
from __future__ import annotations

import json

import pytest

from services import agent_recording as rec
from services.agent_scenarios import load_scenarios, save_scenarios

from tests.services.test_agent_blast import Script, agent_graph


def chat(i=1, **over):
    base = {
        "id": f"run-{i}", "agentId": "app_assistant", "agentName": "Assistant", "who": {"id": "u1", "name": "Lena", "email": "l@x.io", "role": "Support"},
        "message": f"How many open tickets are there? ({i})", "reply": "There are 3 open tickets.", "status": "done",
        "totals": {"ms": 4200, "inputTokens": 900, "outputTokens": 80, "modelCalls": 2, "toolCalls": 1}, "recordedAt": 1_700_000_000,
        "phases": [{"phase": "input_check", "ok": True}],
        "steps": [{"kind": "model", "n": 1, "ms": 1500, "inputTokens": 400, "outputTokens": 40, "toolsRequested": ["list_tickets"], "said": ""},
                  {"kind": "tool", "tool": "list_tickets", "status": "ok", "ms": 80, "input": {"status": "open"}, "result": {"data": [{"id": "t-1"}], "total": 3},
                   "calls": [{"kind": "request", "label": "GET /api/tickets", "method": "GET", "status": 200, "ms": 60, "ok": True}]}],
    }
    return {**base, **over}


# ── cleaning what the page sent ─────────────────────────────────────────────

def test_a_finished_chat_is_kept_with_its_steps_and_details():
    kept = rec.clean_chat(chat())
    assert kept["id"] == "run-1" and kept["who"] == {"id": "u1", "name": "Lena", "email": "l@x.io", "role": "Support"}
    assert kept["reply"] == "There are 3 open tickets." and kept["totals"]["toolCalls"] == 1
    tool = [s for s in kept["steps"] if s["kind"] == "tool"][0]
    assert tool["input"] == {"status": "open"} and tool["result"]["total"] == 3 and tool["calls"][0]["status"] == 200
    assert [s["kind"] for s in kept["steps"]] == ["model", "tool"] and kept["phases"] == [{"phase": "input_check", "ok": True}]


def test_what_is_not_a_finished_chat_is_left_out_and_counted():
    raw = [chat(1), chat(2, status="running"), chat(3, message=""), "nonsense", None, chat(1), chat(4, agentId="another_agent"), chat(5, agentId="")]
    kept, left_out = rec.clean_chats(raw, "app_assistant")
    assert [c["id"] for c in kept] == ["run-1", "run-5"], "running, empty, not a chat, a repeat and another assistant's are out; no agent named is kept"
    assert left_out == 6


def test_big_things_are_cut_and_the_count_is_bounded():
    huge = {"rows": ["x" * 100] * 200}
    kept = rec.clean_chat(chat(message="m" * 5000, reply="r" * 9000,
                               steps=[{"kind": "tool", "tool": "t", "status": "ok", "input": {}, "result": huge}] * 100))
    assert len(kept["message"]) == 2000 and len(kept["reply"]) == 4000 and len(kept["steps"]) == 40
    assert kept["steps"][0]["result"]["_cut"] is True and len(kept["steps"][0]["result"]["preview"]) == 2500
    many, left_out = rec.clean_chats([chat(i) for i in range(60)])
    assert len(many) == rec.MAX_SENT and left_out == 60 - rec.MAX_SENT


def test_an_unknown_step_or_status_cannot_get_in():
    kept = rec.clean_chat(chat(steps=[{"kind": "evil", "x": 1}, {"kind": "tool", "tool": "t", "status": "pwned", "input": 1}]))
    assert len(kept["steps"]) == 1 and kept["steps"][0]["status"] == "failed", "an unknown tool status is taken as a failure, never trusted"
    assert rec.clean_chat(chat(status="hacked")) is None


# ── what went wrong ─────────────────────────────────────────────────────────

def test_a_good_chat_has_no_problems_and_each_kind_of_trouble_is_named():
    assert rec.problems_of(rec.clean_chat(chat())) == []
    bad = rec.clean_chat(chat(status="error", error="boom", reply="", totals={"ms": 41_000},
                              steps=[{"kind": "tool", "tool": "update_ticket", "status": "failed", "error": "403", "input": {},
                                      "problems": [{"code": "missing", "message": "id is required"}]},
                                     {"kind": "model", "failed": "overloaded"}],
                              phases=[{"phase": "output_check", "ok": False, "reason": "leaks a secret"}]))
    said = " ".join(rec.problems_of(bad))
    for part in ("The chat failed: boom", "update_ticket failed: 403", "bad input: id is required", "A call to the AI failed: overloaded",
                 "output check: leaks a secret", "41 seconds"):
        assert part in said, part
    assert "no reply" in " ".join(rec.problems_of(rec.clean_chat(chat(reply=""))))
    assert "refused the message" in " ".join(rec.problems_of(rec.clean_chat(chat(status="blocked", blocked="too long", reply=""))))


# ── the saved test ──────────────────────────────────────────────────────────

def test_each_chat_becomes_a_saved_test_that_knows_what_really_happened():
    ok, bad = rec.clean_chat(chat(1)), rec.clean_chat(chat(2, status="error", error="boom", reply=""))
    a, b = rec.scenario_for(ok), rec.scenario_for(bad)
    assert a["id"] == rec.scenario_id(ok) and a["id"].startswith("rec_") and a["id"] != b["id"] and a["kind"] == "recorded"
    assert a["message"] == ok["message"] and a["name"].startswith("Real chat: How many open tickets")
    assert "went well" in a["judge"] and "went wrong" in b["judge"] and "boom" in b["judge"] and len(b["judge"]) <= 300
    assert rec.scenario_for(rec.clean_chat(chat(3, status="blocked", blocked="too long", reply="")))["expect"] == {"blocked": True}


# ── sending ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sending_keeps_the_chats_adds_tests_and_never_touches_the_builders_own(tmp_path):
    save_scenarios(tmp_path, "app_assistant", [{"name": "Mine", "message": "Hello there", "expect": {}}])
    out = await rec.send(tmp_path, "app_assistant", [chat(1), chat(2, status="error", error="boom", reply="")])
    assert (out["sent"], out["added"], out["alreadyThere"], out["leftOut"]) == (2, 2, 0, 0) and out["fixes"] == []
    saved = load_scenarios(tmp_path, "app_assistant")
    assert [s["name"] for s in saved][0] == "Mine" and len(saved) == 3 and sum(s.get("kind") == "recorded" for s in saved) == 2
    assert list(out["problems"]) == [rec.scenario_id(rec.clean_chat(chat(2)))] and len(out["tests"]) == 2
    kept = rec.load_recordings(tmp_path, "app_assistant")
    assert [c["id"] for c in kept] == ["run-1", "run-2"] and kept[0]["steps"][1]["result"]["total"] == 3, "every detail is kept for later"
    again = await rec.send(tmp_path, "app_assistant", [chat(1), chat(3)])
    assert (again["added"], again["alreadyThere"]) == (1, 1) and len(load_scenarios(tmp_path, "app_assistant")) == 4
    assert [c["id"] for c in rec.load_recordings(tmp_path, "app_assistant")] == ["run-1", "run-2", "run-3"]


@pytest.mark.asyncio
async def test_there_must_be_a_finished_chat_of_this_assistant_to_send(tmp_path):
    with pytest.raises(ValueError, match="Record some chats first"):
        await rec.send(tmp_path, "app_assistant", [chat(1, status="running"), chat(2, agentId="other")])
    with pytest.raises(ValueError, match="as drawn"):
        await rec.send(tmp_path, "app_assistant", [chat(1)], fix=True)


@pytest.mark.asyncio
async def test_the_fixer_reads_the_real_chats_and_its_fixes_name_the_saved_tests(tmp_path):
    bad = chat(2, message="Close ticket T-9", reply="Done.", steps=[{"kind": "tool", "tool": "update_ticket", "status": "failed", "error": "403 Forbidden", "input": {"id": "T-9"}}])
    sid = rec.scenario_id(rec.clean_chat(bad))
    model = Script(fix={"fixes": [
        {"kind": "instruction_add", "text": "When closing a ticket fails, say so and do not claim it is done.", "title": "Say when a change fails", "why": "It said Done after a 403.", "fixes_tests": [sid, "invented-id"]},
        {"kind": "tool_description", "tool": "no_such_tool", "text": "x"},
    ]})
    out = await rec.send(tmp_path, "app_assistant", [chat(1), bad], graph=agent_graph(), fix=True, client=model)
    seen = model.who("fix")
    assert len(seen) == 1
    asked = seen[0]["messages"][0]["content"]
    assert "REAL CHATS" in asked and "Close ticket T-9" in asked and "update_ticket" in asked and "403 Forbidden" in asked and "The tool update_ticket failed" in asked
    assert "REAL CHATS, NOT TESTS" in seen[0]["system"], "the fixer is told these are real chats and not tests"
    assert [f["kind"] for f in out["fixes"]] == ["instruction_add"], "a fix for a tool that is not there is dropped"
    assert out["fixes"][0]["fixesTests"] == [sid], "and it names only the saved tests that exist"
    assert sid in {t["id"] for t in out["tests"]}


@pytest.mark.asyncio
async def test_the_fixer_may_find_nothing_to_fix(tmp_path):
    model = Script(fix={"fixes": []})
    out = await rec.send(tmp_path, "app_assistant", [chat(1)], graph=agent_graph(), fix=True, client=model)
    assert out["fixes"] == [] and out["problems"] == {} and out["added"] == 1


# ── the endpoint ────────────────────────────────────────────────────────────

@pytest.fixture()
def route(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import routers.agent_builder as ab

    holder = SimpleNamespace(output_dir=str(tmp_path))

    async def fake_get(project_id, user, db):
        return holder

    monkeypatch.setattr(ab, "get_project_with_auth", fake_get)
    return ab, holder


@pytest.mark.asyncio
async def test_the_endpoint_sends_and_says_plainly_when_it_cannot(route, tmp_path):
    import uuid

    from fastapi import HTTPException

    from schemas.agent_builder import AgentRecordingSend

    ab, holder = route
    pid = uuid.uuid4()
    out = await ab.send_recorded_chats(pid, "app_assistant", AgentRecordingSend(chats=[chat(1)]), None, None)
    assert out["added"] == 1 and len(load_scenarios(tmp_path, "app_assistant")) == 1
    with pytest.raises(HTTPException) as nothing:
        await ab.send_recorded_chats(pid, "app_assistant", AgentRecordingSend(chats=[]), None, None)
    assert nothing.value.status_code == 400 and "Record some chats first" in nothing.value.detail
    with pytest.raises(HTTPException) as nograph:
        await ab.send_recorded_chats(pid, "app_assistant", AgentRecordingSend(chats=[chat(1)], fix=True), None, None)
    assert nograph.value.status_code == 400
    holder.output_dir = None
    with pytest.raises(HTTPException) as unbuilt:
        await ab.send_recorded_chats(pid, "app_assistant", AgentRecordingSend(chats=[chat(1)]), None, None)
    assert unbuilt.value.status_code == 400 and "not been built" in unbuilt.value.detail
