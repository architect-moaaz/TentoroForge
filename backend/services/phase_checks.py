"""Uniform validate → repair → retry gates for the pipeline spine (O3).

Every phase that has a machine-checkable postcondition gets a declarative
``PhaseCheck``: a validator, an optional deterministic repair, and a bounded
attempt count. The spine inserts one ``<phase>_gate`` node after each phase
with checks (see ``pipeline_graph``): validate → on failure run the repair →
re-validate, up to ``max_attempts``; whatever is STILL failing is quarantined
— appended to ``contracts/quarantine.json`` and carried in pipeline state —
instead of silently shipping or hard-failing the build. The ship report (V3)
folds the quarantine into the final verdict.

This replaces the relay's bespoke per-phase retry loops with one mechanism,
one artifact, and one place to add the next check.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

QUARANTINE_FILE = os.path.join("src", "contracts", "quarantine.json")

# (output_dir, plan) -> (passed, issues). Issues are JSON-serializable.
Validator = Callable[[str, dict], "tuple[bool, list]"]
# (output_dir, plan) -> None. Deterministic, idempotent.
Repairer = Callable[[str, dict], None]


@dataclass
class PhaseCheck:
    name: str
    validate: Validator
    repair: Repairer | None = None
    max_attempts: int = 2
    # strict=True → unresolved issues raise instead of quarantining
    # (used by the binding gate under FORGE_BINDING_GATE=strict).
    strict: bool = False


def run_check(check: PhaseCheck, output_dir: str, plan: dict) -> dict:
    """validate → repair → re-validate, bounded. Never raises from the
    validator/repair themselves (a crashed check quarantines as its own
    issue); raises RuntimeError only for strict checks that end unresolved."""
    attempts = 0
    try:
        passed, issues = check.validate(output_dir, plan)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[phase-gate] %s validator crashed", check.name)
        return {"check": check.name, "passed": False, "attempts": 0,
                "unresolved": [{"kind": "validator_crash", "detail": str(exc)}]}

    while not passed and check.repair is not None and attempts < check.max_attempts:
        attempts += 1
        try:
            check.repair(output_dir, plan)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[phase-gate] %s repair attempt %d crashed: %s",
                           check.name, attempts, exc)
            break
        try:
            passed, issues = check.validate(output_dir, plan)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[phase-gate] %s re-validate crashed", check.name)
            issues = [{"kind": "validator_crash", "detail": str(exc)}]
            break

    result = {"check": check.name, "passed": bool(passed), "attempts": attempts,
              "unresolved": [] if passed else list(issues or [])}
    if not passed and check.strict:
        raise RuntimeError(
            f"[phase-gate] strict check '{check.name}' unresolved after "
            f"{attempts} repair attempt(s): {len(result['unresolved'])} issue(s)")
    return result


def write_quarantine(output_dir: str, entries: list[dict]) -> None:
    """Persist the running quarantine list — the ship report's input."""
    try:
        path = Path(output_dir) / QUARANTINE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"quarantine": entries}, indent=2, default=str),
                        encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.exception("[phase-gate] quarantine persist failed")


# ── concrete checks per phase ────────────────────────────────────────────

def _contracts_validate(output_dir: str, plan: dict):
    from services.phase_gates import check_contract_completeness
    gate = check_contract_completeness(output_dir, plan)
    return gate["passed"], [{"kind": "contract_missing", "detail": m}
                            for m in gate.get("missing", [])]


def _contracts_repair(output_dir: str, plan: dict) -> None:
    from services.contract_generator import generate_contracts
    generate_contracts(output_dir, plan)


def _schema_validate(output_dir: str, plan: dict):
    from routers.generate import _schema_files_complete
    ok = _schema_files_complete(output_dir, plan)
    return ok, ([] if ok else [{"kind": "schema_incomplete",
                                "detail": "drizzle schema / types files incomplete"}])


def _schema_repair(output_dir: str, plan: dict) -> None:
    from services.schema_builder import build_schema_files
    build_schema_files(plan, output_dir)


def _pages_coverage_validate(output_dir: str, plan: dict):
    from services.phase_gates import check_pages_coverage
    cov = check_pages_coverage(output_dir, plan)
    return cov["passed"], [{"kind": "page_schema_missing", "detail": m}
                           for m in cov.get("missing", [])]


def _bindings_validate(output_dir: str, plan: dict):
    from services.binding_validator import validate_bindings
    res = validate_bindings(output_dir)
    return bool(res.get("ok")), list(res.get("errors") or [])


def _binding_gate_strict() -> bool:
    return (os.environ.get("FORGE_BINDING_GATE") or "").strip().lower() == "strict"


def checks_for(phase: str) -> list[PhaseCheck]:
    """The declarative registry. ``finish`` checks run AFTER the post-generate
    guard suite, so binding errors there are what is genuinely still broken."""
    registry: dict[str, list[PhaseCheck]] = {
        "contracts": [PhaseCheck("contract_completeness",
                                 _contracts_validate, _contracts_repair)],
        "schema": [PhaseCheck("schema_files_complete",
                              _schema_validate, _schema_repair)],
        "pages": [PhaseCheck("pages_coverage", _pages_coverage_validate)],
        "finish": [PhaseCheck("binding_contract", _bindings_validate,
                              strict=_binding_gate_strict())],
    }
    return registry.get(phase, [])


def run_phase_gate(phase: str, output_dir: str, plan: dict) -> list[dict]:
    """Run every check registered for a phase; returns per-check results."""
    return [run_check(c, output_dir, plan) for c in checks_for(phase)]
