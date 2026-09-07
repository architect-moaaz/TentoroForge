"""Tests for the FIX intent + chat orchestration (Fix-Assistant, Task 1-D).

Covered:
- the deterministic FIX pre-classifier gate (symptom → FIX, feature-add → REFINE),
  in both directions, through ``looks_like_fix``, ``_fallback_classify`` and the
  short-circuit in ``classify_intent`` (which must NOT call the model);
- the SSE event contract builders (``fix_proposal`` / ``fix_applied`` shapes);
- the pending-fix store/retrieve helpers round-tripping a Diagnosis through
  ``Conversation.metadata_``;
- the ``[APPLY_FIX]`` path in ``_handle_apply_fix``: retrieve the stashed
  Diagnosis → call ``apply_fix`` (stubbed) → emit ``fix_applied``;
- the proposal path in ``_handle_fix_proposal``: diagnose (stubbed) → stash +
  emit ``fix_proposal``; low-confidence → clarifying question, no proposal.

No real model is ever called (the diagnoser/applier are stubbed).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import agents.orchestrator as orch


# --------------------------------------------------------------------------- #
# 1. Classifier — symptom → FIX, feature-add → REFINE
# --------------------------------------------------------------------------- #

FIX_SYMPTOMS = [
    "Creating an assessment crashes",
    "Scheduling an assessment fails to save",
    "the calendar is empty",
    "I can't upload a CV",
    "the dashboard shows nothing",
    "the save button is broken",
    "error: candidate_id is a timestamp",
    "The form isn't working",
]

FEATURE_ADDS = [
    "add a field",
    "make it dark mode",
    "add a search bar to the task list",
    "add validation to the email field",
    "add error handling to the upload",
    "create a new report page",
    "change the card layout to a table",
]


@pytest.mark.parametrize("msg", FIX_SYMPTOMS)
def test_looks_like_fix_true_for_symptoms(msg):
    assert orch.looks_like_fix(msg) is True


@pytest.mark.parametrize("msg", FEATURE_ADDS)
def test_looks_like_fix_false_for_feature_adds(msg):
    assert orch.looks_like_fix(msg) is False


def test_looks_like_fix_empty():
    assert orch.looks_like_fix("") is False
    assert orch.looks_like_fix(None) is False  # type: ignore[arg-type]


@pytest.mark.parametrize("msg", FIX_SYMPTOMS)
def test_fallback_classify_symptom_is_fix(msg):
    # has_files=True, no pending plan → FIX.
    assert orch._fallback_classify(msg, has_files=True) == "FIX"


@pytest.mark.parametrize("msg", FEATURE_ADDS)
def test_fallback_classify_feature_add_is_not_fix(msg):
    assert orch._fallback_classify(msg, has_files=True) != "FIX"


def test_fallback_classify_no_code_never_fix():
    # A symptom on a project with NO code is not a FIX (nothing to repair).
    assert orch._fallback_classify("the form is broken", has_files=False) == "PLAN"


def test_fallback_classify_pending_plan_suppresses_fix():
    # With a plan pending approval, symptom-ish language shouldn't become FIX.
    assert orch._fallback_classify("looks broken", has_files=True, has_pending_plan=True) != "FIX"


def test_classify_intent_short_circuits_to_fix_without_model(tmp_path, monkeypatch):
    """classify_intent must return FIX from the deterministic gate on a has-code
    project WITHOUT invoking the LLM query()."""
    # Give the dir a real file so has_files is True.
    (tmp_path / "app-model.json").write_text("{}", encoding="utf-8")

    def _boom(*a, **k):  # the model must never be called
        raise AssertionError("classify_intent hit the model on a gated FIX symptom")

    monkeypatch.setattr(orch, "query", _boom)
    monkeypatch.setattr(orch, "billing_safe_query", _boom)

    result = asyncio.run(orch.classify_intent(
        "Scheduling an assessment fails to save", str(tmp_path),
    ))
    assert result["intent"] == "FIX"


# --------------------------------------------------------------------------- #
# 2. SSE event contract builders
# --------------------------------------------------------------------------- #

def _diagnosis() -> dict:
    return {
        "symptom": "Scheduling an assessment fails to save",
        "feature": "Schedule an assessment for a candidate",
        "rootCause": "candidateId is written as CURRENT_TIMESTAMP (a uuid column)",
        "explanation": "The workflow writes the current time into the candidate field.",
        "artifact": {"kind": "workflow", "path": "workflows/assessmentschedulingworkflow.json"},
        "locator": {"nodeId": "create_assessment_record", "jsonPointer": None},
        "proposedFix": {"seam": "workflow_node_config",
                        "patch": {"values": {"candidateId": "{{candidateId}}"}}},
        "confidence": 0.82,
        "explanation_extra": "ignored",
    }


def test_fix_proposal_event_shape():
    import json
    from sse_helpers import fix_proposal_event

    changes = [{"node": "create_assessment_record", "field": "candidateId",
                "from": "CURRENT_TIMESTAMP", "to": "{{candidateId}}"}]
    ev = fix_proposal_event(_diagnosis(), changes)
    assert ev["event"] == "fix_proposal"
    data = json.loads(ev["data"])
    assert set(data.keys()) == {"diagnosis", "changes", "applyToken"}
    assert data["applyToken"] == "[APPLY_FIX]"
    assert data["changes"] == changes
    d = data["diagnosis"]
    assert set(d.keys()) == {
        "symptom", "feature", "rootCause", "explanation",
        "artifact", "locator", "confidence",
    }
    assert d["artifact"] == {"kind": "workflow",
                             "path": "workflows/assessmentschedulingworkflow.json"}
    assert d["locator"] == {"nodeId": "create_assessment_record", "jsonPointer": None}
    assert d["confidence"] == 0.82


def test_fix_applied_event_shape():
    import json
    from sse_helpers import fix_applied_event

    result = {
        "applied": True,
        "seam": "workflow_node_config",
        "changes": [{"node": "n1", "field": "candidateId",
                     "from": "CURRENT_TIMESTAMP", "to": "{{candidateId}}"}],
        "verify": {"resolved": True, "remaining": []},
        "committed": True,
    }
    ev = fix_applied_event(result, "Done — the fix is applied.")
    assert ev["event"] == "fix_applied"
    data = json.loads(ev["data"])
    assert set(data.keys()) == {"applied", "changes", "verify", "committed", "message"}
    assert data["applied"] is True
    assert data["committed"] is True
    assert data["verify"] == {"resolved": True, "remaining": []}
    assert data["message"] == "Done — the fix is applied."


def test_fix_applied_event_coerces_missing_fields():
    import json
    from sse_helpers import fix_applied_event

    ev = fix_applied_event({}, "n/a")
    data = json.loads(ev["data"])
    assert data["applied"] is False
    assert data["committed"] is False
    assert data["changes"] == []
    assert data["verify"] == {"resolved": False, "remaining": []}


# --------------------------------------------------------------------------- #
# 3. Pending-fix store / retrieve round-trip (pure — no DB)
# --------------------------------------------------------------------------- #

def test_pending_fix_metadata_and_find_roundtrip():
    import routers.generate as g

    diag = _diagnosis()
    meta = g._pending_fix_metadata(diag)
    assert meta["intent"] == "FIX"
    assert meta["applyToken"] == "[APPLY_FIX]"
    assert meta["pending_fix"] == diag

    # A conversation-like object carrying that metadata round-trips.
    conv = SimpleNamespace(metadata_=meta)
    assert g._find_pending_fix([conv]) == diag


def test_find_pending_fix_returns_newest_first():
    import routers.generate as g

    newer = SimpleNamespace(metadata_={"pending_fix": {"id": "new"}})
    older = SimpleNamespace(metadata_={"pending_fix": {"id": "old"}})
    # loader passes newest-first; _find_pending_fix returns the first hit.
    assert g._find_pending_fix([newer, older]) == {"id": "new"}


def test_find_pending_fix_none_when_absent():
    import routers.generate as g

    assert g._find_pending_fix([]) is None
    assert g._find_pending_fix([SimpleNamespace(metadata_=None)]) is None
    assert g._find_pending_fix([SimpleNamespace(metadata_={"intent": "REFINE"})]) is None


# --------------------------------------------------------------------------- #
# 4. [APPLY_FIX] path — retrieve stashed Diagnosis → call apply_fix (stub)
# --------------------------------------------------------------------------- #

def _collect(agen) -> list:
    async def _run():
        out = []
        async for ev in agen:
            out.append(ev)
        return out
    return asyncio.run(_run())


def test_handle_apply_fix_retrieves_and_applies(monkeypatch):
    import json
    import routers.generate as g
    import services.fix_applier as fa

    diag = _diagnosis()
    captured = {}

    async def _fake_load(project_id):
        return diag

    async def _noop_persist(*a, **k):
        return None

    def _fake_apply(output_dir, diagnosis, git=True):
        captured["output_dir"] = output_dir
        captured["diagnosis"] = diagnosis
        captured["git"] = git
        return {
            "applied": True,
            "seam": "workflow_node_config",
            "changes": [{"node": "create_assessment_record", "field": "candidateId",
                         "from": "CURRENT_TIMESTAMP", "to": "{{candidateId}}"}],
            "verify": {"resolved": True, "remaining": []},
            "committed": False,
        }

    async def _fake_mode(_pid):
        return "single_shot"

    monkeypatch.setattr(g, "_load_pending_fix", _fake_load)
    monkeypatch.setattr(g, "_load_pending_fix_mode", _fake_mode)
    monkeypatch.setattr(g, "_persist_assistant_message", _noop_persist)
    monkeypatch.setattr(g, "_clear_pending_fix", _noop_persist)
    monkeypatch.setattr(fa, "apply_fix", _fake_apply)

    project = SimpleNamespace(id="p1", output_dir="/tmp/app")
    events = _collect(g._handle_apply_fix(project))

    # apply_fix was called with the retrieved diagnosis.
    assert captured["diagnosis"] == diag
    assert captured["output_dir"] == "/tmp/app"

    # A fix_applied event was emitted with the pinned shape.
    applied = [e for e in events if e["event"] == "fix_applied"]
    assert len(applied) == 1
    data = json.loads(applied[0]["data"])
    assert data["applied"] is True
    assert data["verify"] == {"resolved": True, "remaining": []}
    assert data["changes"][0]["field"] == "candidateId"


def test_handle_apply_fix_without_pending(monkeypatch):
    import json
    import routers.generate as g

    async def _no_pending(project_id):
        return None

    async def _noop_persist(*a, **k):
        return None

    monkeypatch.setattr(g, "_load_pending_fix", _no_pending)
    monkeypatch.setattr(g, "_persist_assistant_message", _noop_persist)

    project = SimpleNamespace(id="p1", output_dir="/tmp/app")
    events = _collect(g._handle_apply_fix(project))

    # No fix_applied — just a plain message asking to re-describe.
    assert not any(e["event"] == "fix_applied" for e in events)
    msgs = [e for e in events if e["event"] == "message"]
    assert msgs and "pending fix" in json.loads(msgs[0]["data"])["text"].lower()


# --------------------------------------------------------------------------- #
# 5. Proposal path — diagnose (stub) → stash + emit fix_proposal
# --------------------------------------------------------------------------- #

def test_handle_fix_proposal_confident_stashes_and_emits(monkeypatch, tmp_path):
    import json
    import routers.generate as g
    import agents.fix_diagnoser as fd

    diag = _diagnosis()
    persisted = {}

    def _fake_diagnose(symptom, output_dir, *, recall=None, resource_ctx=None):
        return dict(diag, symptom=symptom)

    async def _capture_persist(project_id, content, message_type, metadata=None):
        persisted["content"] = content
        persisted["metadata"] = metadata

    async def _no_pending(_pid):
        return None

    monkeypatch.setattr(fd, "diagnose", _fake_diagnose)
    monkeypatch.setattr(g, "_persist_assistant_message", _capture_persist)
    monkeypatch.setattr(g, "_load_pending_fix", _no_pending)

    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))
    events = _collect(g._handle_fix_proposal(project, "Scheduling fails to save"))

    # The diagnosis was stashed in the assistant turn metadata.
    assert persisted["metadata"]["intent"] == "FIX"
    assert persisted["metadata"]["pending_fix"]["symptom"] == "Scheduling fails to save"

    # A fix_proposal event was emitted with the [APPLY_FIX] chip.
    proposals = [e for e in events if e["event"] == "fix_proposal"]
    assert len(proposals) == 1
    data = json.loads(proposals[0]["data"])
    assert data["applyToken"] == "[APPLY_FIX]"
    assert data["diagnosis"]["confidence"] == 0.82


def test_handle_fix_proposal_low_confidence_asks_clarifying(monkeypatch, tmp_path):
    import json
    import routers.generate as g
    import agents.fix_diagnoser as fd

    low = dict(_diagnosis(), confidence=0.1,
               explanation="Could you share the exact screen or the error you see?")
    persisted = {}

    def _fake_diagnose(symptom, output_dir, *, recall=None, resource_ctx=None):
        return low

    async def _capture_persist(project_id, content, message_type, metadata=None):
        persisted["metadata"] = metadata

    async def _no_pending(_pid):
        return None

    monkeypatch.setattr(fd, "diagnose", _fake_diagnose)
    monkeypatch.setattr(g, "_persist_assistant_message", _capture_persist)
    monkeypatch.setattr(g, "_load_pending_fix", _no_pending)

    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))
    events = _collect(g._handle_fix_proposal(project, "something is off"))

    # No proposal / no stashed pending_fix — just a clarifying message.
    assert not any(e["event"] == "fix_proposal" for e in events)
    assert "pending_fix" not in (persisted.get("metadata") or {})
    msgs = [e for e in events if e["event"] == "message"]
    assert msgs and "screen" in json.loads(msgs[0]["data"])["text"].lower()


# ── Live bug repro: "Can you fix it?" must not clobber a pending proposal ─────
# In the reported chat: turn 1 diagnosed correctly + stashed pending_fix.
# Turn 2 "Can you fix it?" clobbered it with a "couldn't pin that down"
# clarifying question. These two tests lock the two branches of the fix.

def test_handle_fix_proposal_routes_apply_intent_to_apply_when_pending(monkeypatch, tmp_path):
    """When there's a pending_fix and the user says 'Can you fix it?' / 'yes'
    / 'apply', we route to _handle_apply_fix instead of re-diagnosing."""
    import json as _json
    import routers.generate as g
    import agents.fix_diagnoser as fd

    diag = _diagnosis()
    async def _has_pending(_pid): return diag
    def _boom_diagnose(*a, **k):
        raise AssertionError("diagnose should NOT run when routing to apply")
    async def _fake_apply_gen(_project):
        yield {"event": "fix_applied", "data": _json.dumps({"applied": True})}
    monkeypatch.setattr(g, "_load_pending_fix", _has_pending)
    monkeypatch.setattr(fd, "diagnose", _boom_diagnose)
    monkeypatch.setattr(g, "_handle_apply_fix", _fake_apply_gen)

    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))
    events = _collect(g._handle_fix_proposal(project, "Can you fix it?"))
    kinds = [e["event"] for e in events]
    assert "fix_applied" in kinds
    assert "fix_proposal" not in kinds


def test_handle_fix_proposal_reemits_pending_on_low_confidence_refinement(monkeypatch, tmp_path):
    """When there's a pending_fix and the follow-up isn't apply-intent (e.g.
    the user provides more context like 'Page is Assessment Scheduling'), a
    fresh low-confidence diagnosis must NOT drop the pending — re-emit it."""
    import routers.generate as g
    import agents.fix_diagnoser as fd

    pending = dict(_diagnosis(), symptom="scheduling fails to save")
    low = dict(_diagnosis(), confidence=0.1, artifact={},
               explanation="I couldn't pin that down.")
    async def _has_pending(_pid): return pending
    def _fake_diagnose(symptom, output_dir, *, recall=None, resource_ctx=None):
        return low
    async def _capture_persist(project_id, content, message_type, metadata=None):
        _capture_persist.md = metadata
    monkeypatch.setattr(g, "_load_pending_fix", _has_pending)
    monkeypatch.setattr(fd, "diagnose", _fake_diagnose)
    monkeypatch.setattr(g, "_persist_assistant_message", _capture_persist)

    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))
    events = _collect(g._handle_fix_proposal(project, "Page is Assessment Scheduling"))

    # The pending proposal was RE-EMITTED as a fix_proposal (not lost).
    proposals = [e for e in events if e["event"] == "fix_proposal"]
    assert proposals, f"expected fix_proposal, got events {[e['event'] for e in events]}"
    # And it was stashed again so [APPLY_FIX] still works on the next turn.
    assert _capture_persist.md.get("pending_fix", {}).get("symptom") == pending["symptom"]


# ────────────────────────────────────────────────────────────
# _find_pending_fix — Smith-trace fallback
# ────────────────────────────────────────────────────────────

from types import SimpleNamespace

from routers.generate import _find_pending_fix, _find_pending_fix_mode


def _conv(md):
    """Fake Conversation shape — only ``metadata_`` is read."""
    return SimpleNamespace(metadata_=md)


def test_find_pending_fix_prefers_top_level():
    """When both are present, top-level ``pending_fix`` wins over the trace
    (that's the canonical spot the single-shot path stashes at)."""
    top = {"rootCause": "top-level"}
    trace = {"rootCause": "in-trace"}
    conv = _conv({
        "pending_fix": top,
        "smith_trace": [
            {"tool": "propose_fix", "args": {"diagnosis": trace}},
        ],
    })
    assert _find_pending_fix([conv]) == top


def test_find_pending_fix_falls_back_to_smith_trace():
    """The Smith-tool-loop path leaves ``propose_fix.args.diagnosis`` in the
    trace but doesn't lift to top-level. Apply must still find it — this
    is the Drive-details case: user clicked Apply on a Smith diagnosis
    that only lived inside the trace."""
    diagnosis = {"rootCause": "detail page missing three related sections",
                 "confidence": 0.92}
    conv = _conv({
        "intent": "SMITH",
        "smith_trace": [
            {"tool": "read_page", "args": {"path": "x"}},
            {"tool": "think",     "args": {"thought": "…"}},
            {"tool": "propose_fix", "args": {"diagnosis": diagnosis}},
        ],
    })
    assert _find_pending_fix([conv]) == diagnosis


def test_find_pending_fix_picks_last_propose_fix_in_trace():
    """If Smith proposed twice in one turn (rare — repeated diagnosis),
    the newer one wins. Same reversal the frontend does."""
    older = {"rootCause": "first attempt"}
    newer = {"rootCause": "second attempt"}
    conv = _conv({
        "smith_trace": [
            {"tool": "propose_fix", "args": {"diagnosis": older}},
            {"tool": "think",       "args": {"thought": "reconsider"}},
            {"tool": "propose_fix", "args": {"diagnosis": newer}},
        ],
    })
    assert _find_pending_fix([conv]) == newer


def test_find_pending_fix_ignores_non_propose_fix_trace_steps():
    conv = _conv({
        "smith_trace": [
            {"tool": "read_page",   "args": {"path": "x"}},
            {"tool": "verify_promise", "args": {"claim": "x"}},
        ],
    })
    assert _find_pending_fix([conv]) is None


def test_find_pending_fix_returns_none_when_no_metadata():
    conv = _conv(None)
    assert _find_pending_fix([conv]) is None


def test_find_pending_fix_mode_from_trace_is_agent():
    """A trace-derived diagnosis is agent-mode by construction — the Smith
    tool loop is the only thing that emits smith_trace steps."""
    diagnosis = {"rootCause": "x"}
    conv = _conv({
        "smith_trace": [{"tool": "propose_fix", "args": {"diagnosis": diagnosis}}],
    })
    assert _find_pending_fix_mode([conv]) == "agent"


def test_find_pending_fix_mode_top_level_wins_over_trace():
    """Explicit mode declaration always wins."""
    conv = _conv({
        "pending_fix": {"rootCause": "x"},
        "pending_fix_mode": "single_shot",
        "smith_trace": [{"tool": "propose_fix", "args": {"diagnosis": {}}}],
    })
    assert _find_pending_fix_mode([conv]) == "single_shot"
