"""Tests for the decision-ledger instrumentation in action_contract_guard.

Covers _record_action_decisions + _fuzzy_workflow_alternatives:
- Resolved action → high band, no chip
- Unresolved with fuzzy match → low band, "did you mean" alternative
- Unresolved with no fuzzy candidates → low band, empty alternatives
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.action_contract_guard import (
    _fuzzy_workflow_alternatives, _record_action_decisions,
)
from services.decision_ledger import (
    BAND_HIGH, BAND_LOW, KIND_BUTTON_TARGET, KIND_FORM_SUBMIT, load_ledger,
)


# ── _fuzzy_workflow_alternatives: pure edit-distance helper ────────

def test_fuzzy_finds_close_workflow_names():
    """Typoed reference should surface the correct workflow as top hit."""
    workflows = ["PublishArticle", "DeleteArticle", "ArchiveArticle"]
    alts = _fuzzy_workflow_alternatives("PublshArticle", workflows)
    assert alts
    assert alts[0][0] == "PublishArticle"
    assert alts[0][1] > 0.6


def test_fuzzy_ignores_low_score_noise():
    """Wildly different names shouldn't appear as alternatives."""
    workflows = ["UnrelatedWorkflow", "AnotherThing"]
    alts = _fuzzy_workflow_alternatives("Publish", workflows)
    assert alts == []  # nothing close enough


def test_fuzzy_returns_empty_for_empty_ref():
    assert _fuzzy_workflow_alternatives("", ["Anything"]) == []


def test_fuzzy_returns_empty_for_empty_catalog():
    assert _fuzzy_workflow_alternatives("Anything", []) == []


def test_fuzzy_top_k_bound():
    """Even if many workflows match, cap at top_k."""
    workflows = [f"Workflow{i}" for i in range(20)]
    alts = _fuzzy_workflow_alternatives("Workflow5", workflows, top_k=3)
    assert len(alts) <= 3


# ── _record_action_decisions: ledger side-effect ──────────────────

def test_resolved_action_writes_high_band_row(tmp_path: Path):
    """Successful workflow match ships silent (high band) — audit trail only."""
    workflows = {"publisharticle": {"id": "wf1", "name": "PublishArticle"}}
    actions = [{
        "file": "articles/edit.json",
        "kind": "button",
        "label": "Publish",
        "workflow_ref": "PublishArticle",
        "workflow_id": "wf1",
        "resolved": True,
    }]
    _record_action_decisions(str(tmp_path), actions, workflows)

    rows = [r for r in load_ledger(str(tmp_path))
            if r["kind"] == KIND_BUTTON_TARGET]
    assert len(rows) == 1
    assert rows[0]["confidence"] == BAND_HIGH
    assert rows[0]["target_picked"] == "wf1"
    assert rows[0]["identity"] == "Publish"
    assert "file:articles/edit.json" in rows[0]["scope"]


def test_unresolved_with_fuzzy_writes_low_band_with_suggestions(tmp_path: Path):
    """Typoed workflow ref surfaces as chip with 'did you mean' alternatives."""
    workflows = {
        "publisharticle": {"id": "wf1", "name": "PublishArticle"},
        "deletearticle":  {"id": "wf2", "name": "DeleteArticle"},
    }
    actions = [{
        "file": "articles/edit.json",
        "kind": "button",
        "label": "Publish",
        "workflow_ref": "PublshArticle",  # typo
        "workflow_id": None,
        "resolved": False,
    }]
    # Pass the workflow NAMES (not norm keys) — the real caller
    # iterates workflows.keys() which are norm-lowered, but the fuzzy
    # helper needs the real names. Simulate by giving _record the
    # workflows dict shape it sees.
    _record_action_decisions(str(tmp_path), actions,
                             {"PublishArticle": workflows["publisharticle"],
                              "DeleteArticle": workflows["deletearticle"]})

    rows = [r for r in load_ledger(str(tmp_path))
            if r["kind"] == KIND_BUTTON_TARGET]
    assert len(rows) == 1
    assert rows[0]["confidence"] == BAND_LOW
    assert rows[0]["target_picked"].startswith("unresolved:")
    assert any(a["target"] == "PublishArticle"
               for a in rows[0]["alternatives"])


def test_unresolved_with_no_candidates_still_writes_row(tmp_path: Path):
    """Even with zero fuzzy matches, the miss surfaces — user needs
    to know the workflow ref is dead."""
    actions = [{
        "file": "widgets/panel.json",
        "kind": "button",
        "label": "DoThing",
        "workflow_ref": "TotallyMadeUp",
        "workflow_id": None,
        "resolved": False,
    }]
    _record_action_decisions(str(tmp_path), actions,
                             {"UnrelatedThing": {"id": "wf1"}})

    rows = load_ledger(str(tmp_path))
    assert len(rows) == 1
    assert rows[0]["confidence"] == BAND_LOW
    assert rows[0]["alternatives"] == []
    assert "no similar workflows" in (rows[0]["reason"] or "")


def test_form_kind_maps_to_form_submit_decision_kind(tmp_path: Path):
    """Form actions use KIND_FORM_SUBMIT, buttons use KIND_BUTTON_TARGET."""
    actions = [{
        "file": "signup.json",
        "kind": "form",
        "label": "SignupForm",
        "workflow_ref": "CreateUser",
        "workflow_id": "wf1",
        "resolved": True,
    }]
    _record_action_decisions(str(tmp_path), actions,
                             {"CreateUser": {"id": "wf1"}})
    rows = load_ledger(str(tmp_path))
    assert len(rows) == 1
    assert rows[0]["kind"] == KIND_FORM_SUBMIT


def test_actions_without_workflow_ref_skipped(tmp_path: Path):
    """Nothing to record for actions that don't reference a workflow."""
    actions = [{
        "file": "x.json", "kind": "button", "label": "X",
        "workflow_ref": None, "resolved": False,
    }]
    _record_action_decisions(str(tmp_path), actions, {})
    assert load_ledger(str(tmp_path)) == []
