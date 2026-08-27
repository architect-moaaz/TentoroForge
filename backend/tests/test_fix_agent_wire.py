"""Tests for the FORGE_FIX_AGENT wiring in routers.generate (Slice 3, Task 3-C).

- Flag OFF: current single-shot handler unchanged (byte-identical shape).
- Flag ON: `_handle_fix_proposal` delegates to `run_fix_agent` (stubbed) and
  emits the same event shapes; agent trace is stashed on the assistant turn.
- Both agent branches — diagnosis vs question — round-trip through the SSE.
- Pending-fix + apply-intent short-circuit still runs BEFORE the agent (the
  agent is not invoked when the user consented to apply the last proposal).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _collect(agen) -> list:
    async def _run():
        out = []
        async for ev in agen:
            out.append(ev)
        return out
    return asyncio.run(_run())


def _diagnosis() -> dict:
    return {
        "symptom": "scheduling fails",
        "feature": "Schedule an assessment",
        "rootCause": "candidateId is written as CURRENT_TIMESTAMP",
        "explanation": "The workflow writes now() into the candidate FK.",
        "artifact": {"kind": "workflow",
                     "path": "workflows/CreateAssessment.json"},
        "locator": {"nodeId": "create_assessment_record", "jsonPointer": None},
        "proposedFix": {"seam": "workflow_node_config",
                        "patch": {"values": {"candidateId": "{{candidateId}}"}}},
        "confidence": 0.82,
        "validation": {"clean": True, "remaining": []},
    }


# --------------------------------------------------------------------------- #
# Flag OFF: current path unchanged.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("env_val", ["", "0", "false", "off", "no"])
def test_flag_off_uses_single_shot_diagnoser(monkeypatch, tmp_path, env_val):
    """When FORGE_FIX_AGENT is empty/0/false/off/no, run_fix_agent must NOT
    be called; the classic diagnoser path runs unchanged."""
    import routers.generate as g
    import agents.fix_diagnoser as fd
    import agents.fix_chat_agent as fca

    monkeypatch.setenv("FORGE_FIX_AGENT", env_val)

    def _boom_agent(*a, **k):  # agent must not run
        raise AssertionError("run_fix_agent must not be called with FORGE_FIX_AGENT off")

    monkeypatch.setattr(fca, "run_fix_agent", _boom_agent)

    diag = _diagnosis()

    def _fake_diagnose(symptom, output_dir, *, recall=None, resource_ctx=None):
        return dict(diag, symptom=symptom)

    async def _no_pending(_pid): return None
    async def _persist(*a, **k): return None

    monkeypatch.setattr(fd, "diagnose", _fake_diagnose)
    monkeypatch.setattr(g, "_load_pending_fix", _no_pending)
    monkeypatch.setattr(g, "_persist_assistant_message", _persist)

    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))
    events = _collect(g._handle_fix_proposal(project, "Scheduling fails to save"))
    kinds = [e["event"] for e in events]
    # Same events the pre-agent path emits.
    assert "status" in kinds
    assert "fix_proposal" in kinds


# --------------------------------------------------------------------------- #
# Flag ON: agent branch — diagnosis → fix_proposal + trace stashed
# --------------------------------------------------------------------------- #

def test_flag_on_diagnosis_emits_fix_proposal_and_trace(monkeypatch, tmp_path):
    import routers.generate as g
    import agents.fix_chat_agent as fca
    import agents.fix_diagnoser as fd

    monkeypatch.setenv("FORGE_FIX_AGENT", "1")

    diag = _diagnosis()
    trace = [
        {"tool": "recall", "args": {}, "result_summary": "..."},
        {"tool": "read_workflow", "args": {"path": "workflows/CreateAssessment.json"},
         "result_summary": "..."},
        {"tool": "propose_fix", "args": {"diagnosis": diag},
         "result_summary": "propose_fix"},
    ]

    def _fake_agent(symptom, output_dir, recall_block, **_):
        return {"diagnosis": dict(diag, symptom=symptom),
                "question": None, "trace": trace}

    def _boom_diag(*a, **k):
        raise AssertionError("single-shot diagnose must not run when agent is on")

    persisted = {}

    async def _capture_persist(project_id, content, message_type, metadata=None):
        persisted["metadata"] = metadata
        persisted["content"] = content

    async def _no_pending(_pid): return None

    monkeypatch.setattr(fca, "run_fix_agent", _fake_agent)
    monkeypatch.setattr(fd, "diagnose", _boom_diag)
    monkeypatch.setattr(g, "_load_pending_fix", _no_pending)
    monkeypatch.setattr(g, "_persist_assistant_message", _capture_persist)

    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))
    events = _collect(g._handle_fix_proposal(project, "Scheduling fails to save"))

    # Same SSE contract the frontend already consumes.
    proposals = [e for e in events if e["event"] == "fix_proposal"]
    assert len(proposals) == 1
    data = json.loads(proposals[0]["data"])
    assert data["applyToken"] == "[APPLY_FIX]"
    assert data["diagnosis"]["artifact"]["path"] == "workflows/CreateAssessment.json"
    assert data["diagnosis"]["confidence"] == 0.82

    # The agent trace is attached to the assistant turn metadata.
    md = persisted["metadata"]
    assert md["intent"] == "FIX"
    assert md["applyToken"] == "[APPLY_FIX]"
    assert md["pending_fix"]["artifact"]["path"] == "workflows/CreateAssessment.json"
    assert md["fix_agent_trace"] == trace


# --------------------------------------------------------------------------- #
# Flag ON: agent branch — question → plain message + trace on metadata
# --------------------------------------------------------------------------- #

def test_flag_on_question_emits_message_and_trace(monkeypatch, tmp_path):
    import routers.generate as g
    import agents.fix_chat_agent as fca

    monkeypatch.setenv("FORGE_FIX_AGENT", "1")

    trace = [{"tool": "recall", "args": {}, "result_summary": "..."},
             {"tool": "ask_user", "args": {"question": "which screen?"},
              "result_summary": "ask_user"}]

    def _fake_agent(symptom, output_dir, recall_block, **_):
        return {"diagnosis": None,
                "question": "Which screen were you on when it failed?",
                "trace": trace}

    persisted = {}

    async def _capture_persist(project_id, content, message_type, metadata=None):
        persisted["metadata"] = metadata
        persisted["content"] = content

    async def _no_pending(_pid): return None

    monkeypatch.setattr(fca, "run_fix_agent", _fake_agent)
    monkeypatch.setattr(g, "_load_pending_fix", _no_pending)
    monkeypatch.setattr(g, "_persist_assistant_message", _capture_persist)

    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))
    events = _collect(g._handle_fix_proposal(project, "stuff is broken"))

    # No fix_proposal; a plain message with the question.
    assert not any(e["event"] == "fix_proposal" for e in events)
    msgs = [e for e in events if e["event"] == "message"]
    assert msgs, [e["event"] for e in events]
    assert "Which screen" in json.loads(msgs[-1]["data"])["text"]

    # No pending_fix stashed, but trace is present.
    assert "pending_fix" not in (persisted["metadata"] or {})
    assert persisted["metadata"]["fix_agent_trace"] == trace


# --------------------------------------------------------------------------- #
# Flag ON: pending + apply intent still short-circuits BEFORE the agent
# --------------------------------------------------------------------------- #

def test_flag_on_pending_and_apply_intent_short_circuits(monkeypatch, tmp_path):
    """The short-circuit added in ff617c7 must still fire BEFORE the agent."""
    import routers.generate as g
    import agents.fix_chat_agent as fca

    monkeypatch.setenv("FORGE_FIX_AGENT", "1")

    def _boom_agent(*a, **k):
        raise AssertionError("agent must not run when the user consented to apply")

    async def _has_pending(_pid): return _diagnosis()

    async def _fake_apply_gen(_project):
        yield {"event": "fix_applied", "data": json.dumps({"applied": True})}

    monkeypatch.setattr(fca, "run_fix_agent", _boom_agent)
    monkeypatch.setattr(g, "_load_pending_fix", _has_pending)
    monkeypatch.setattr(g, "_handle_apply_fix", _fake_apply_gen)

    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))
    events = _collect(g._handle_fix_proposal(project, "yes fix it"))
    kinds = [e["event"] for e in events]
    assert "fix_applied" in kinds
    assert "fix_proposal" not in kinds


# --------------------------------------------------------------------------- #
# Flag ON: pending + no-diagnosis follow-up → RE-EMIT the pending
# --------------------------------------------------------------------------- #

def test_flag_on_pending_reemitted_when_agent_asks_question(monkeypatch, tmp_path):
    """Same guarantee as the single-shot path: a pending proposal must not be
    silently lost when the agent decides to clarify."""
    import routers.generate as g
    import agents.fix_chat_agent as fca

    monkeypatch.setenv("FORGE_FIX_AGENT", "1")

    pending = _diagnosis()

    def _fake_agent(symptom, output_dir, recall_block, **_):
        return {"diagnosis": None, "question": "which page?", "trace": []}

    async def _has_pending(_pid): return pending

    persisted = {}

    async def _capture_persist(project_id, content, message_type, metadata=None):
        persisted["metadata"] = metadata

    monkeypatch.setattr(fca, "run_fix_agent", _fake_agent)
    monkeypatch.setattr(g, "_load_pending_fix", _has_pending)
    monkeypatch.setattr(g, "_persist_assistant_message", _capture_persist)

    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))
    events = _collect(g._handle_fix_proposal(project, "Page is Assessment Scheduling"))

    # The pending proposal WAS re-emitted (not lost).
    proposals = [e for e in events if e["event"] == "fix_proposal"]
    assert proposals, [e["event"] for e in events]
    # And re-stashed so [APPLY_FIX] on the next turn still works.
    assert persisted["metadata"].get("pending_fix", {}).get("artifact", {}).get("path") \
        == "workflows/CreateAssessment.json"


# --------------------------------------------------------------------------- #
# Flag helper isolation
# --------------------------------------------------------------------------- #

def test_fix_agent_enabled_helper(monkeypatch):
    import routers.generate as g

    monkeypatch.delenv("FORGE_FIX_AGENT", raising=False)
    assert g._fix_agent_enabled() is False

    for on in ("1", "true", "on", "yes", "ON", "TRUE"):
        monkeypatch.setenv("FORGE_FIX_AGENT", on)
        assert g._fix_agent_enabled() is True

    for off in ("", "0", "false", "OFF", "no"):
        monkeypatch.setenv("FORGE_FIX_AGENT", off)
        assert g._fix_agent_enabled() is False
