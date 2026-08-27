"""Router integration for Smith — the FORGE_SMITH gate + _handle_smith_turn
event stream.

Follows the same monkeypatch style as test_fix_orchestration — the loop,
recall, memory, persist, and apply seams are all stubbed so the tests
run instantly with no model calls and no DB.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest


def _collect(agen) -> list:
    async def _run():
        out = []
        async for ev in agen:
            out.append(ev)
        return out
    return asyncio.run(_run())


# --------------------------------------------------------------------------- #
# FORGE_SMITH flag semantics
# --------------------------------------------------------------------------- #

def test_smith_enabled_default_off(monkeypatch):
    """Flag unset → OFF; keeps behaviour byte-compatible until you opt in.

    Uses setenv('') rather than delenv because config.load_dotenv() may
    have already populated os.environ from backend/.env at import time —
    an empty explicit override matches the 'unset' path in _smith_enabled
    (which treats '' the same as unset)."""
    monkeypatch.setenv("FORGE_SMITH", "")
    import routers.generate as g
    assert g._smith_enabled() is False


@pytest.mark.parametrize("val", ["", "0", "false", "off", "no", "FALSE"])
def test_smith_enabled_falsey_values_are_off(monkeypatch, val):
    monkeypatch.setenv("FORGE_SMITH", val)
    import routers.generate as g
    assert g._smith_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "on", "yes", "YES", "True"])
def test_smith_enabled_truthy_values_are_on(monkeypatch, val):
    monkeypatch.setenv("FORGE_SMITH", val)
    import routers.generate as g
    assert g._smith_enabled() is True


# --------------------------------------------------------------------------- #
# _looks_conversational — pre-classifier greeting/small-talk detector
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("msg", [
    "Hi", "hi", "HI!", "Hello", "Hey", "hey there",
    "Good morning", "Good afternoon", "Howdy!",
    "who are you?", "What can you do?", "how does this work",
    "help", "sup", "yo", "hola",
])
def test_looks_conversational_catches_greetings_and_meta(msg):
    import routers.generate as g
    assert g._looks_conversational(msg), f"{msg!r} should be conversational"


@pytest.mark.parametrize("msg", [
    "Build me a patient management system for a clinic",
    "Create an HR leave management tool for a mid-sized company",
    "Add a Kanban view of applications by stage on the pipeline page",
    "Fix the Schedule button — nothing happens when I click it",
    "Change the primary color to green",
    "Remove the analytics dashboard, we're not using it",
    "I want an app that lets me track equipment maintenance across sites",
])
def test_looks_conversational_lets_build_requests_through(msg):
    """Real app descriptions / refinement requests must NOT match — they need
    to reach the classifier + planner as before."""
    import routers.generate as g
    assert not g._looks_conversational(msg), (
        f"{msg!r} should flow to the classifier, not Smith's greeting path"
    )


def test_looks_conversational_handles_empty_and_non_strings():
    import routers.generate as g
    assert g._looks_conversational("") is False
    assert g._looks_conversational("   ") is False
    assert g._looks_conversational(None) is False
    assert g._looks_conversational(123) is False


# --------------------------------------------------------------------------- #
# _handle_smith_turn — the three terminals map to the right SSE events
# --------------------------------------------------------------------------- #

def _stub_router(monkeypatch, agent_result):
    """Wire monkeypatches so _handle_smith_turn runs against fakes.

    - _load_pending_fix returns None (no pending, so no short-circuit).
    - _persist_assistant_message is a noop that records the last kwargs.
    - assemble_recall / read_smith_memory return empty blocks.
    - run_smith_agent returns ``agent_result`` verbatim.
    """
    import routers.generate as g
    import services.app_recall as ar
    import services.smith_memory as sm
    import agents.smith_agent as sa

    captured = {"persisted": []}

    async def _no_pending(_pid):
        return None

    async def _persist(project_id, content, message_type, metadata=None):
        captured["persisted"].append({
            "content": content,
            "metadata": metadata or {},
        })

    def _empty_recall(_output_dir):
        return SimpleNamespace(to_prompt_block=lambda: "APP INTENT: test")

    async def _empty_memory(*_a, **_kw):
        return SimpleNamespace(to_prompt_block=lambda: "<smith-memory>none</smith-memory>")

    def _fake_agent(user_message, output_dir, recall_block, memory_block,
                    *, prior_messages=None, query_fn=None, max_iters=16,
                    scoped_tools=None, reasoning_callback=None,
                    pending_confirmation=None, **_kw):
        captured["agent_call"] = {
            "user_message": user_message,
            "output_dir": output_dir,
            "recall_block": recall_block,
            "memory_block": memory_block,
            "prior_messages": prior_messages,
            "scoped_tools": scoped_tools,
            "reasoning_callback": reasoning_callback,
        }
        return agent_result

    async def _empty_prior_messages(*_a, **_kw):
        return []

    monkeypatch.setattr(g, "_load_pending_fix", _no_pending)
    monkeypatch.setattr(g, "_persist_assistant_message", _persist)
    monkeypatch.setattr(ar, "assemble_recall", _empty_recall)
    monkeypatch.setattr(sm, "read_smith_memory", _empty_memory)
    monkeypatch.setattr(sm, "load_chat_history_for_prompt", _empty_prior_messages)
    monkeypatch.setattr(sa, "run_smith_agent", _fake_agent)
    return g, captured


def test_smith_turn_answer_streams_message_and_persists(monkeypatch):
    # Test uses /tmp/app (nonexistent). Direct-agent branch is what
    # this test validates; the architect wire's directory-existence
    # gate would otherwise route to the bootstrap fallback.
    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "0")
    result = {
        "diagnosis": None,
        "answer": "The Schedule button triggers the AssessmentScheduling workflow.",
        "question": None,
        "trace": [
            {"tool": "recall", "args": {}, "result_summary": "…"},
            {"tool": "read_workflow", "args": {"path": "w.json"},
             "result_summary": "loaded 8 nodes"},
            {"tool": "answer", "args": {"text": "…"}, "result_summary": "answer"},
        ],
    }
    g, captured = _stub_router(monkeypatch, result)
    project = SimpleNamespace(id="p1", output_dir="/tmp/app")
    events = _collect(g._handle_smith_turn(project, "How does Schedule work?"))

    # smith_thought events precede the terminal message; terminals aren't
    # doubled as thoughts.
    thoughts = [e for e in events if e["event"] == "smith_thought"]
    assert [json.loads(e["data"])["tool"] for e in thoughts] == ["recall", "read_workflow"]

    # Terminal is a plain message event carrying the answer text.
    messages = [e for e in events if e["event"] == "message"]
    assert any("AssessmentScheduling workflow" in json.loads(m["data"])["text"]
               for m in messages)

    # No fix_proposal event on an answer terminal.
    assert not [e for e in events if e["event"] == "fix_proposal"]

    # Persisted turn carries smith_trace + SMITH intent + NO pending_fix.
    assert len(captured["persisted"]) == 1
    md = captured["persisted"][0]["metadata"]
    assert md["intent"] == "SMITH"
    assert md["smith_trace"] == result["trace"]
    assert "pending_fix" not in md


def test_smith_turn_ask_user_streams_question_and_persists(monkeypatch):
    result = {
        "diagnosis": None, "answer": None,
        "question": "Which page were you on when it broke?",
        "trace": [{"tool": "ask_user", "args": {"question": "…"},
                   "result_summary": "ask_user"}],
    }
    g, captured = _stub_router(monkeypatch, result)
    project = SimpleNamespace(id="p1", output_dir="/tmp/app")
    events = _collect(g._handle_smith_turn(project, "it's broken"))

    messages = [e for e in events if e["event"] == "message"]
    assert any("Which page were you on" in json.loads(m["data"])["text"]
               for m in messages)
    # No fix_proposal.
    assert not [e for e in events if e["event"] == "fix_proposal"]


def test_smith_turn_propose_fix_streams_proposal_and_stashes_pending(monkeypatch):
    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "0")
    diag = {
        "feature": "assessment-scheduling",
        "rootCause": "candidateId is CURRENT_TIMESTAMP",
        "artifact": {"kind": "workflow",
                     "path": "workflows/assessmentschedulingworkflow.json"},
        "locator": {"nodeId": "create_assessment_record", "jsonPointer": None},
        "proposedFix": {"seam": "workflow_node_config",
                        "patch": {"values": {"candidateId": "{{candidateId}}"}}},
        "confidence": 0.95,
        "explanation": "Will rebind candidateId to {{candidateId}}.",
    }
    result = {
        "diagnosis": diag, "answer": None, "question": None,
        "trace": [
            {"tool": "recall", "args": {}, "result_summary": "…"},
            {"tool": "propose_fix", "args": {"diagnosis": diag},
             "result_summary": "propose_fix"},
        ],
    }
    g, captured = _stub_router(monkeypatch, result)

    # _preview_fix_changes reads workflows/*.json from disk; stub it too
    # so we don't need a real app tree.
    def _fake_preview(_output_dir, _diagnosis):
        return [{"node": "create_assessment_record", "field": "candidateId",
                 "from": "CURRENT_TIMESTAMP", "to": "{{candidateId}}"}]
    import routers.generate as g_
    import types as _types
    g_._preview_fix_changes = _types.MethodType(
        _fake_preview, g_,
    ) if False else _fake_preview  # simple attr replacement
    monkeypatch.setattr(g_, "_preview_fix_changes", _fake_preview)

    project = SimpleNamespace(id="p1", output_dir="/tmp/app")
    events = _collect(g._handle_smith_turn(project, "schedule broken"))

    # A fix_proposal event was emitted with the pinned shape (per
    # sse_helpers.fix_proposal_event — diagnosis carries artifact/locator/
    # explanation but NOT proposedFix; that lives on the persisted
    # pending_fix metadata for the [APPLY_FIX] chip handler to consume).
    proposals = [e for e in events if e["event"] == "fix_proposal"]
    assert len(proposals) == 1
    proposal_data = json.loads(proposals[0]["data"])
    assert proposal_data["diagnosis"]["artifact"]["path"].endswith(
        "assessmentschedulingworkflow.json"
    )
    assert proposal_data["diagnosis"]["locator"]["nodeId"] == "create_assessment_record"
    assert proposal_data["applyToken"]  # frontend triggers on this
    assert proposal_data["changes"][0]["field"] == "candidateId"

    # Followed by a message event containing the normalized proposal text.
    messages = [e for e in events if e["event"] == "message"]
    assert any("candidateId" in json.loads(m["data"])["text"] for m in messages)

    # Persisted turn carries pending_fix + applyToken (chip flow works
    # unchanged) + smith_trace.
    md = captured["persisted"][0]["metadata"]
    assert md.get("pending_fix") == diag
    assert md.get("applyToken") == "[APPLY_FIX]"
    assert md.get("smith_trace") == result["trace"]


def test_smith_turn_apply_intent_short_circuits_when_pending(monkeypatch):
    """When there's a pending fix and the user says 'yes fix it', the Smith
    turn should skip the loop entirely and route to _handle_apply_fix — same
    rule the fix-agent branch uses (saves a model round-trip)."""
    import routers.generate as g

    diag = {"artifact": {"kind": "workflow", "path": "w.json"},
            "proposedFix": {"seam": "workflow_node_config", "patch": {}},
            "confidence": 0.8}

    async def _has_pending(_pid):
        return diag

    async def _fake_apply(project):
        yield {"event": "fix_applied", "data": json.dumps({"applied": True})}

    monkeypatch.setattr(g, "_load_pending_fix", _has_pending)
    monkeypatch.setattr(g, "_handle_apply_fix", _fake_apply)

    project = SimpleNamespace(id="p1", output_dir="/tmp/app")
    events = _collect(g._handle_smith_turn(project, "yes fix it"))

    # Applied event fired; no smith_thought (never entered the loop).
    assert any(e["event"] == "fix_applied" for e in events)
    assert not any(e["event"] == "smith_thought" for e in events)


def test_smith_turn_survives_agent_crash(monkeypatch):
    """A crash in run_smith_agent must not blow up the SSE stream — it
    should persist a fallback assistant message and yield a friendly one."""
    import routers.generate as g
    import services.app_recall as ar
    import services.smith_memory as sm
    import agents.smith_agent as sa

    async def _no_pending(_pid):
        return None
    async def _noop(*_a, **_kw):
        return None

    def _empty_recall(_o):
        return SimpleNamespace(to_prompt_block=lambda: "")

    async def _empty_memory(*_a, **_kw):
        return SimpleNamespace(to_prompt_block=lambda: "")

    def _boom(*a, **kw):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(g, "_load_pending_fix", _no_pending)
    monkeypatch.setattr(g, "_persist_assistant_message", _noop)
    monkeypatch.setattr(ar, "assemble_recall", _empty_recall)
    monkeypatch.setattr(sm, "read_smith_memory", _empty_memory)
    monkeypatch.setattr(sa, "run_smith_agent", _boom)

    project = SimpleNamespace(id="p1", output_dir="/tmp/app")
    events = _collect(g._handle_smith_turn(project, "hi"))
    messages = [e for e in events if e["event"] == "message"]
    assert messages
    text = json.loads(messages[0]["data"])["text"]
    assert "error" in text.lower() or "rephrase" in text.lower()
