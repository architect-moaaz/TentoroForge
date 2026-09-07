"""Tests for services.scorecard — the merged per-app quality scorecard.

The scorecard is a PURE READER over the report artifacts a generation
already writes (proof, delivery gate, page-contract, binding smoke,
validators, action contract, page critic, anatomy, requirement
fidelity, and — runtime tier — visual QA / visual regression /
journeys). It re-runs nothing, tolerates absent or unreadable files,
and emits two headline numbers plus a per-source breakdown.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.scorecard import SCORECARD_REL, build_scorecard, write_scorecard


# ───────────────────────────── fixtures ─────────────────────────────

def _app(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    (root / "contracts").mkdir(parents=True)
    return root


def _put(root: Path, rel: str, data) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


# ─────────────────────────── empty app ──────────────────────────────

def test_all_absent_scores_clean(tmp_path):
    root = _app(tmp_path)
    card = build_scorecard(root)
    assert card["functional_score"] == 100
    assert card["design_score"] == 100
    assert card["composite"] == 100
    assert card["tier"] == "static"
    assert card["inputs"]["proof_report"] == "absent"
    assert card["inputs"]["page_critic"] == "absent"


def test_unreadable_report_flagged_not_fatal(tmp_path):
    root = _app(tmp_path)
    (root / "contracts" / "proof_report.json").write_text("{not json", encoding="utf-8")
    card = build_scorecard(root)
    assert card["inputs"]["proof_report"] == "unreadable"
    assert card["functional_score"] == 100


# ─────────────────────── functional sources ─────────────────────────

def test_proof_scores_distinct_codes_not_raw_counts(tmp_path):
    """20 repeats of one broken pattern = ONE class of defect. Raw
    counts let a single noisy check hit the cap (the blessed reference
    app did, on undefined-ref alone)."""
    root = _app(tmp_path)
    _put(root, "contracts/proof_report.json",
         {"passed": False, "error_count": 21, "warning_count": 3,
          "findings": (
             [{"severity": "error", "code": "undefined-ref"}] * 20
             + [{"severity": "error", "code": "duplicate-route"}]
             + [{"severity": "warning", "code": "list-without-repeat"}] * 3)})
    card = build_scorecard(root)
    # 2 distinct error codes *8 + 1 distinct warning code *2 = 18
    assert card["breakdown"]["proof"]["penalty"] == 18
    assert card["breakdown"]["proof"]["error_codes"] == \
        ["duplicate-route", "undefined-ref"]
    assert card["functional_score"] == 82
    assert card["design_score"] == 100


def test_proof_penalty_capped(tmp_path):
    root = _app(tmp_path)
    _put(root, "contracts/proof_report.json",
         {"passed": False, "error_count": 6, "warning_count": 0,
          "findings": [{"severity": "error", "code": f"c{i}"}
                       for i in range(6)]})
    card = build_scorecard(root)
    assert card["breakdown"]["proof"]["penalty"] == 40      # 6*8 capped
    assert card["functional_score"] == 60


def test_delivery_gate_vocabulary(tmp_path):
    root = _app(tmp_path)
    _put(root, "contracts/delivery-report.json",
         {"violations": [], "summary": {"error": 1, "warn": 2, "info": 9}})
    card = build_scorecard(root)
    # 1*5 + 2*1 = 7; info never penalizes
    assert card["breakdown"]["delivery"]["penalty"] == 7
    assert card["functional_score"] == 93


def test_page_contract_and_binding_smoke(tmp_path):
    root = _app(tmp_path)
    _put(root, "contracts/page-contract.json",
         {"issues": [], "summary": {"pages": 8, "errors": 2, "skipped": 0}})
    _put(root, "contracts/binding-smoke.json",
         {"mode": "warn", "summary": {"error": 1, "info": 4}, "findings": []})
    card = build_scorecard(root)
    assert card["breakdown"]["page_contract"]["penalty"] == 6   # 2*3
    assert card["breakdown"]["binding_smoke"]["penalty"] == 3   # 1*3
    assert card["functional_score"] == 91


def test_proof_aggregated_validators_informational_only(tmp_path):
    """workflow/contract validation findings are already folded into
    proof_report by proof_pass — penalizing the standalone files too
    would double-count. rules_validation is NOT aggregated and does
    penalize."""
    root = _app(tmp_path)
    _put(root, "contracts/workflow_validation.json",
         [{"severity": "error", "code": "X"},
          {"severity": "warning", "code": "Y"}])
    _put(root, "contracts/contract_validation.json",
         [{"severity": "error", "code": "Z"}])
    _put(root, "contracts/rules_validation.json",
         [{"severity": "error", "code": "R"}])
    card = build_scorecard(root)
    assert card["breakdown"]["workflow_validation"]["penalty"] == 0
    assert card["breakdown"]["workflow_validation"]["errors"] == 1
    assert card["breakdown"]["contract_validation"]["penalty"] == 0
    assert card["breakdown"]["rules_validation"]["penalty"] == 2
    assert card["functional_score"] == 98


def test_action_contract_unresolved_derived(tmp_path):
    root = _app(tmp_path)
    _put(root, "contracts/action-contract.json",
         {"version": 1, "actions": [
             {"file": "a.json", "resolved": True},
             {"file": "b.json", "resolved": False},
             {"file": "c.json", "resolved": False},
         ]})
    card = build_scorecard(root)
    assert card["breakdown"]["action_contract"]["unresolved"] == 2
    assert card["breakdown"]["action_contract"]["penalty"] == 6   # 2*3
    assert card["functional_score"] == 94


# ───────────────────────── design sources ───────────────────────────

def test_page_critic_pass_rate(tmp_path):
    root = _app(tmp_path)
    _put(root, "reports/page-critic/summary.json",
         {"total_pages": 10, "pages_passed": 5, "pages_failed": 5,
          "pass_rate": 0.5, "avg_score": 61})
    card = build_scorecard(root)
    assert card["breakdown"]["page_critic"]["penalty"] == 20     # (1-0.5)*40
    assert card["design_score"] == 80
    assert card["functional_score"] == 100


def test_anatomy_unfilled_slots(tmp_path):
    root = _app(tmp_path)
    _put(root, "contracts/page-anatomy.json",
         {"findings": [], "summary": {"injected": 4, "reported": 2}})
    card = build_scorecard(root)
    assert card["breakdown"]["anatomy"]["penalty"] == 6          # 2*3
    assert card["design_score"] == 94


def test_requirement_fidelity_src_contracts_dir(tmp_path):
    root = _app(tmp_path)
    _put(root, "src/contracts/requirement-fidelity.json",
         {"verdicts": [], "summary": {"ok": 6, "missing": 2, "partial": 1}})
    card = build_scorecard(root)
    assert card["breakdown"]["requirement_fidelity"]["penalty"] == 12  # 2*5+1*2
    assert card["design_score"] == 88


# ─────────────────────── composite + output ─────────────────────────

def test_composite_is_min_of_the_two(tmp_path):
    root = _app(tmp_path)
    _put(root, "contracts/proof_report.json",
         {"error_count": 1, "warning_count": 0,
          "findings": [{"severity": "error", "code": "x"}]})           # func 92
    _put(root, "reports/page-critic/summary.json",
         {"total_pages": 4, "pages_passed": 1, "pass_rate": 0.25})     # design 70
    card = build_scorecard(root)
    assert card["functional_score"] == 92
    assert card["design_score"] == 70
    assert card["composite"] == 70


def test_timing_total_from_generation_timing(tmp_path):
    root = _app(tmp_path)
    _put(root, "generation-timing.json", {"plan": 10.5, "schema": 20.0})
    card = build_scorecard(root)
    assert card["timing"]["total_s"] == 30.5


def test_write_scorecard_persists(tmp_path):
    root = _app(tmp_path)
    _put(root, "contracts/proof_report.json",
         {"error_count": 1, "warning_count": 0,
          "findings": [{"severity": "error", "code": "x"}]})
    card = write_scorecard(root)
    on_disk = json.loads((root / SCORECARD_REL).read_text(encoding="utf-8"))
    assert on_disk["functional_score"] == card["functional_score"] == 92
    assert "generated_at" in on_disk


def test_write_scorecard_never_raises(tmp_path):
    # output dir doesn't even exist
    card = write_scorecard(tmp_path / "nope")
    assert card["functional_score"] == 100


# ─────────────────────────── runtime tier ───────────────────────────

def test_static_tier_ignores_runtime_reports(tmp_path):
    root = _app(tmp_path)
    _put(root, "contracts/visual-qa.json",
         {"pages_reviewed": ["/"], "findings": [
             {"kind": "overflow", "severity": "error", "route": "/"}]})
    card = build_scorecard(root)                       # static
    assert "visual_qa" not in card["breakdown"]
    assert card["design_score"] == 100


def test_runtime_tier_counts_visual_qa_and_regression(tmp_path):
    root = _app(tmp_path)
    _put(root, "contracts/visual-qa.json",
         {"pages_reviewed": ["/"], "findings": [
             {"kind": "overflow", "severity": "error", "route": "/"},
             {"kind": "raw_label", "severity": "warn", "route": "/x"}]})
    _put(root, "contracts/visual-regression.json",
         {"tolerance": 0.02, "results": [],
          "summary": {"ok": 3, "changed": 1, "layout_changed": 2,
                      "new": 0, "missing": 0}})
    card = build_scorecard(root, tier="runtime")
    assert card["tier"] == "runtime"
    assert card["breakdown"]["visual_qa"]["penalty"] == 6        # 1*5+1*1
    assert card["breakdown"]["visual_regression"]["penalty"] == 6  # 2*3
    assert card["design_score"] == 88


def test_runtime_tier_journey_failures(tmp_path):
    root = _app(tmp_path)
    _put(root, "journey-remediation-report.json",
         {"app_slug": "x", "mode": "warn",
          "summary": {"total": 4, "passed": 2, "failed": 2},
          "journeys": [{"slug": "a", "status": "failed"},
                       {"slug": "b", "status": "failed"}]})
    card = build_scorecard(root, tier="runtime")
    # failed/total * 25 = 12.5
    assert card["breakdown"]["journeys"]["penalty"] == 12.5
    assert card["functional_score"] == 87.5
