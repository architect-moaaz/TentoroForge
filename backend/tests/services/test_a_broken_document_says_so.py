"""A Blueprint that was already invalid says so, instead of blaming the change.

The whole document is validated on every commit, so one bad key anywhere makes
every write fail — and the error names the broken section, which is rarely the
one being written. It reads exactly like a rejected proposal.

Measured on a 50-page application: `runtime.placeholders`, an empty list left
by a since-removed producer. Every write to that project had been failing ever
since. A composition that was demonstrably valid — it passed
`check_pattern_templates` — came back refused, twice, and two rounds of
investigation went into the composition before anyone validated the untouched
document, which fails in one line.
"""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, apply_agent_result,
)
from services.blueprint.service import BlueprintInvalid, BlueprintService


def _svc(tmp_path):
    return BlueprintService.create(
        output_dir=str(tmp_path), app_id="app", name="App",
        domain="test", description="a test application",
    )


def _a_page(svc):
    return AgentResult(
        task_id="TASK-1", agent="page_design", confidence=1.0,
        proposals=[ArtifactProposal(
            section="pages",
            natural_key="/",
            body={"route": "/", "name": "Home", "pattern": "dashboard",
                  "purpose": "the landing screen"},
        )],
    )


def test_a_pre_existing_fault_is_named_as_pre_existing(tmp_path):
    svc = _svc(tmp_path)
    # A key from an older schema version, exactly as it was found on disk.
    svc.doc.setdefault("runtime", {})["placeholders"] = []

    with pytest.raises(BlueprintInvalid) as exc:
        apply_agent_result(svc, _a_page(svc), commit=False, user_request="x")

    said = str(exc.value)
    assert "ALREADY invalid before the change" in said
    # And it still names the actual fault, so the message is actionable.
    assert "placeholders" in said


def test_the_original_fault_survives_in_errors(tmp_path):
    """The list is what a caller reads programmatically; the added line must
    not displace what was actually wrong."""
    svc = _svc(tmp_path)
    svc.doc.setdefault("runtime", {})["placeholders"] = []

    with pytest.raises(BlueprintInvalid) as exc:
        apply_agent_result(svc, _a_page(svc), commit=False, user_request="x")
    assert any("placeholders" in e for e in exc.value.errors)


def test_nothing_is_repaired_or_loosened(tmp_path):
    """The document is still invalid and the write is still refused. Only the
    attribution changes — a repair here would be the quiet fix §76 forbids."""
    svc = _svc(tmp_path)
    svc.doc.setdefault("runtime", {})["placeholders"] = []

    with pytest.raises(BlueprintInvalid):
        apply_agent_result(svc, _a_page(svc), commit=False, user_request="x")

    assert svc.doc["runtime"]["placeholders"] == [], "the fault was repaired"
    assert not [p for p in svc.doc.get("pages") or [] if p.get("route") == "/"], (
        "the refused change was left behind")


def test_a_genuinely_bad_proposal_is_still_blamed_on_the_proposal(tmp_path):
    """The other direction, and the one that matters: on a healthy document
    the message must not start claiming the document was already broken."""
    svc = _svc(tmp_path)
    bad = AgentResult(
        task_id="TASK-2", agent="page_design", confidence=1.0,
        proposals=[ArtifactProposal(
            section="pages", natural_key="/x",
            body={"route": "/x", "name": "X", "pattern": "dashboard",
                  "purpose": "p", "notAField": True},
        )],
    )
    with pytest.raises(BlueprintInvalid) as exc:
        apply_agent_result(svc, bad, commit=False, user_request="x")
    assert "ALREADY invalid" not in str(exc.value)
