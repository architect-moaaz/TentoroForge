"""Merged per-app quality scorecard.

One number pair per generated app — ``functional_score`` (does it
work) and ``design_score`` (does it look considered) — derived by
READING the report artifacts the pipeline already writes. Nothing is
re-run: absent artifacts contribute no penalty and are recorded in
``inputs`` so a scorecard is honest about what it saw. This is the
comparison substrate for the fixture fleet: two generations (or the
same fixture before/after a platform change) can be diffed on the
breakdown, not just the headline.

Sources normalized here span three summary vocabularies and four
directories (``contracts/``, ``src/contracts/``, app root,
``reports/``); four reports carry no summary at all (bare Finding
arrays) so their counts are derived. Composite is the MIN of the two
scores — a beautiful broken app must not outrank a plain working one.

Spec: docs/superpowers/plans/2026-08-17-fixture-fleet-scorecard.md (S1).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCORECARD_REL = "contracts/scorecard.json"

# (source name, path relative to app root)
_FUNCTIONAL_SOURCES = {
    "proof_report": "contracts/proof_report.json",
    "delivery": "contracts/delivery-report.json",
    "page_contract": "contracts/page-contract.json",
    "binding_smoke": "contracts/binding-smoke.json",
    "workflow_validation": "contracts/workflow_validation.json",
    "contract_validation": "contracts/contract_validation.json",
    "rules_validation": "contracts/rules_validation.json",
    "action_contract": "contracts/action-contract.json",
}
_DESIGN_SOURCES = {
    "page_critic": "reports/page-critic/summary.json",
    "anatomy": "contracts/page-anatomy.json",
    "requirement_fidelity": "src/contracts/requirement-fidelity.json",
}
_RUNTIME_SOURCES = {
    "visual_qa": "contracts/visual-qa.json",
    "visual_regression": "contracts/visual-regression.json",
    "journeys": "journey-remediation-report.json",
}
_TIMING_REL = "generation-timing.json"


def _read(root: Path, rel: str, inputs: dict[str, str], name: str) -> Any:
    path = root / rel
    if not path.is_file():
        inputs[name] = "absent"
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        inputs[name] = "unreadable"
        return None
    inputs[name] = "ok"
    return data


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _capped(raw: float, cap: float) -> float:
    penalty = min(raw, cap)
    return round(penalty, 1)


def build_scorecard(output_dir: str | Path, tier: str = "static") -> dict:
    """Score an existing generated app from its report artifacts."""
    root = Path(output_dir)
    inputs: dict[str, str] = {}
    breakdown: dict[str, dict] = {}
    functional_penalty = 0.0
    design_penalty = 0.0

    # ── functional ──────────────────────────────────────────────────
    proof = _read(root, _FUNCTIONAL_SOURCES["proof_report"], inputs,
                  "proof_report")
    if isinstance(proof, dict):
        # Distinct CODES, not raw findings: one broken pattern repeated on
        # 20 workflows is one class of defect (fixes land per class), and
        # raw counts let a single noisy check dominate the whole score —
        # the blessed reference app hit the cap on undefined-ref alone.
        findings = proof.get("findings") or []
        error_codes = {f.get("code") for f in findings
                       if isinstance(f, dict) and f.get("severity") == "error"}
        warn_codes = {f.get("code") for f in findings
                      if isinstance(f, dict)
                      and f.get("severity") == "warning"}
        penalty = _capped(len(error_codes) * 8 + len(warn_codes) * 2, 40)
        breakdown["proof"] = {
            "errors": _num(proof.get("error_count")),
            "warnings": _num(proof.get("warning_count")),
            "error_codes": sorted(c for c in error_codes if c),
            "warning_codes": sorted(c for c in warn_codes if c),
            "penalty": penalty}
        functional_penalty += penalty

    delivery = _read(root, _FUNCTIONAL_SOURCES["delivery"], inputs,
                     "delivery")
    if isinstance(delivery, dict):
        summary = delivery.get("summary") or {}
        errors = _num(summary.get("error"))
        warns = _num(summary.get("warn"))
        penalty = _capped(errors * 5 + warns * 1, 25)
        breakdown["delivery"] = {"errors": errors, "warns": warns,
                                 "penalty": penalty}
        functional_penalty += penalty

    page_contract = _read(root, _FUNCTIONAL_SOURCES["page_contract"],
                          inputs, "page_contract")
    if isinstance(page_contract, dict):
        errors = _num((page_contract.get("summary") or {}).get("errors"))
        penalty = _capped(errors * 3, 15)
        breakdown["page_contract"] = {"errors": errors, "penalty": penalty}
        functional_penalty += penalty

    binding_smoke = _read(root, _FUNCTIONAL_SOURCES["binding_smoke"],
                          inputs, "binding_smoke")
    if isinstance(binding_smoke, dict):
        errors = _num((binding_smoke.get("summary") or {}).get("error"))
        penalty = _capped(errors * 3, 15)
        breakdown["binding_smoke"] = {"errors": errors, "penalty": penalty}
        functional_penalty += penalty

    # Bare-array validator reports. workflow/contract validation findings
    # are ALREADY aggregated into proof_report (services/proof_pass.py) —
    # penalizing them again would double-count, so they're informational.
    # rules_validation is NOT in proof's aggregate and does penalize.
    for name in ("workflow_validation", "contract_validation"):
        findings = _read(root, _FUNCTIONAL_SOURCES[name], inputs, name)
        if isinstance(findings, list):
            errors = sum(1 for f in findings if isinstance(f, dict)
                         and f.get("severity") == "error")
            breakdown[name] = {"errors": errors, "penalty": 0,
                               "note": "aggregated by proof"}
    rules = _read(root, _FUNCTIONAL_SOURCES["rules_validation"], inputs,
                  "rules_validation")
    if isinstance(rules, list):
        errors = sum(1 for f in rules if isinstance(f, dict)
                     and f.get("severity") == "error")
        penalty = _capped(errors * 2, 10)
        breakdown["rules_validation"] = {"errors": errors,
                                         "penalty": penalty}
        functional_penalty += penalty

    action_contract = _read(root, _FUNCTIONAL_SOURCES["action_contract"],
                            inputs, "action_contract")
    if isinstance(action_contract, dict):
        actions = action_contract.get("actions")
        if isinstance(actions, list):
            unresolved = sum(1 for a in actions
                             if isinstance(a, dict)
                             and a.get("resolved") is False)
            penalty = _capped(unresolved * 3, 10)
            breakdown["action_contract"] = {"unresolved": unresolved,
                                            "penalty": penalty}
            functional_penalty += penalty

    # ── design ──────────────────────────────────────────────────────
    critic = _read(root, _DESIGN_SOURCES["page_critic"], inputs,
                   "page_critic")
    if isinstance(critic, dict) and _num(critic.get("total_pages")) > 0:
        pass_rate = _num(critic.get("pass_rate"))
        penalty = _capped((1 - pass_rate) * 40, 40)
        breakdown["page_critic"] = {"pass_rate": pass_rate,
                                    "avg_score": critic.get("avg_score"),
                                    "penalty": penalty}
        design_penalty += penalty

    anatomy = _read(root, _DESIGN_SOURCES["anatomy"], inputs, "anatomy")
    if isinstance(anatomy, dict):
        _asum = anatomy.get("summary") or {}
        # Prefer the actionable count — info-level suggestions and findings
        # the anatomy pass already auto-repaired must not cost points.
        reported = _num(_asum.get("reported_actionable",
                                  _asum.get("reported")))
        penalty = _capped(reported * 3, 15)
        breakdown["anatomy"] = {"unfilled_slots": reported,
                                "penalty": penalty}
        design_penalty += penalty

    fidelity = _read(root, _DESIGN_SOURCES["requirement_fidelity"], inputs,
                     "requirement_fidelity")
    if isinstance(fidelity, dict):
        summary = fidelity.get("summary") or {}
        missing = _num(summary.get("missing"))
        partial = _num(summary.get("partial"))
        penalty = _capped(missing * 5 + partial * 2, 20)
        breakdown["requirement_fidelity"] = {"missing": missing,
                                             "partial": partial,
                                             "penalty": penalty}
        design_penalty += penalty

    # ── runtime tier ────────────────────────────────────────────────
    if tier == "runtime":
        visual_qa = _read(root, _RUNTIME_SOURCES["visual_qa"], inputs,
                          "visual_qa")
        if isinstance(visual_qa, dict):
            findings = visual_qa.get("findings") or []
            errors = sum(1 for f in findings if isinstance(f, dict)
                         and f.get("severity") == "error")
            warns = sum(1 for f in findings if isinstance(f, dict)
                        and f.get("severity") == "warn")
            penalty = _capped(errors * 5 + warns * 1, 15)
            breakdown["visual_qa"] = {"errors": errors, "warns": warns,
                                      "penalty": penalty}
            design_penalty += penalty

        regression = _read(root, _RUNTIME_SOURCES["visual_regression"],
                           inputs, "visual_regression")
        if isinstance(regression, dict):
            layout_changed = _num(
                (regression.get("summary") or {}).get("layout_changed"))
            penalty = _capped(layout_changed * 3, 10)
            breakdown["visual_regression"] = {
                "layout_changed": layout_changed, "penalty": penalty}
            design_penalty += penalty

        journeys = _read(root, _RUNTIME_SOURCES["journeys"], inputs,
                         "journeys")
        if isinstance(journeys, dict):
            summary = journeys.get("summary") or {}
            failed = _num(summary.get("failed"))
            total = _num(summary.get("total"))
            if not failed:
                failed = float(len(journeys.get("journeys") or []))
            if total > 0:
                penalty = round(min(failed / total, 1.0) * 25, 1)
            else:
                penalty = _capped(failed * 5, 25)
            breakdown["journeys"] = {"failed": failed, "total": total,
                                     "penalty": penalty}
            functional_penalty += penalty

    # ── assemble ────────────────────────────────────────────────────
    functional = round(max(0.0, 100 - functional_penalty), 1)
    design = round(max(0.0, 100 - design_penalty), 1)
    card: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tier": tier,
        "functional_score": functional,
        "design_score": design,
        "composite": min(functional, design),
        "inputs": inputs,
        "breakdown": breakdown,
    }

    timing = _read(root, _TIMING_REL, inputs, "timing")
    if isinstance(timing, dict):
        card["timing"] = {"total_s": round(sum(
            v for v in timing.values() if isinstance(v, (int, float))), 1)}

    return card


def write_scorecard(output_dir: str | Path, tier: str = "static") -> dict:
    """Build and persist ``contracts/scorecard.json``. Never raises."""
    try:
        card = build_scorecard(output_dir, tier=tier)
    except Exception:  # noqa: BLE001
        logger.exception("scorecard: build failed for %s", output_dir)
        return {}
    try:
        path = Path(output_dir) / SCORECARD_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.exception("scorecard: write failed for %s", output_dir)
    return card
