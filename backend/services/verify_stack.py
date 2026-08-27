"""Verify stack — 5-check verify pipeline (M5-T5).

Spec P2: every stage output and every Smith turn passes through the
same stack of checks, cheapest first. Cheap checks (<5s) always run;
expensive ones (design critic, runtime render) opt-in per call.

This module is a composition primitive over already-existing check
implementations. It does NOT own the checks themselves:

- ``static`` — delegates to whatever type/JSON-schema check the stage
  provides (or a caller-supplied callable).
- ``structural`` — delegates to ``plan_completeness_validator`` /
  ``shape_profile.validate_all`` / existing registry checks.
- ``domain_conformance`` — delegates to ``shape_profile_derived``
  helpers to check "does this page respect its effective shape."
- ``design_conformance`` — delegates to the design critic
  (expensive, LLM-backed; opt-in).
- ``runtime`` — delegates to the compile / dev-server check
  (expensive; opt-in).

The stack's job is: run the requested checks in order, short-circuit
on first hard failure if the stage asked to, record the results in
``SessionContext.verify_history``, return a structured report.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Optional

from services.session_context import SessionContext, VerifyRecord


CheckName = Literal["static", "structural", "domain_conformance", "design_conformance", "runtime"]


# Cheap tier — always run when requested.
CHEAP_CHECKS: frozenset[CheckName] = frozenset({"static", "structural", "domain_conformance"})
# Expensive tier — opt-in only.
EXPENSIVE_CHECKS: frozenset[CheckName] = frozenset({"design_conformance", "runtime"})
ALL_CHECKS: tuple[CheckName, ...] = ("static", "structural", "domain_conformance", "design_conformance", "runtime")


CheckResult = dict[str, Any]
CheckCallable = Callable[[dict[str, Any], SessionContext], CheckResult]


@dataclass
class VerifyReport:
    """Aggregate output of the verify_stack run."""
    stage: str
    passed: bool
    checks_run: tuple[CheckName, ...]
    findings: list[dict[str, Any]] = field(default_factory=list)
    per_check_ms: dict[str, int] = field(default_factory=dict)
    short_circuited: bool = False

    def has_error(self) -> bool:
        return any((f.get("severity") or "error") == "error" for f in self.findings)


def run_stack(
    stage: str,
    output: dict[str, Any],
    context: SessionContext,
    *,
    checks: Iterable[CheckName] | None = None,
    check_registry: dict[CheckName, CheckCallable] | None = None,
    short_circuit_on_error: bool = False,
) -> VerifyReport:
    """Run the verify stack against ``output``.

    ``checks`` — subset of ALL_CHECKS to run. Defaults to CHEAP_CHECKS
    (the always-safe set). Callers that want expensive checks pass
    them explicitly.

    ``check_registry`` — dict mapping check name → callable. Missing
    callables produce a ``check.not_implemented`` finding at info
    severity and skip cleanly. Callers wire this from the actual
    implementations at wire-time.

    ``short_circuit_on_error`` — when True, stop after the first
    ``error`` finding. Useful for fast-fail during Smith turns.

    Records the report in ``context.verify_history`` and returns it.
    """
    requested: tuple[CheckName, ...] = tuple(checks) if checks else tuple(CHEAP_CHECKS)
    registry = check_registry or {}
    findings: list[dict[str, Any]] = []
    per_check_ms: dict[str, int] = {}
    ran: list[CheckName] = []
    short_circuited = False

    for check in requested:
        if check not in ALL_CHECKS:
            findings.append({
                "rule": "verify_stack.unknown_check",
                "message": f"unknown check {check!r}; expected one of {list(ALL_CHECKS)}",
                "severity": "warning",
                "check": check,
            })
            continue
        fn = registry.get(check)
        start = time.monotonic()
        if fn is None:
            findings.append({
                "rule": "verify_stack.check_not_implemented",
                "message": f"check {check!r} not registered by caller",
                "severity": "info",
                "check": check,
            })
            per_check_ms[check] = 0
            ran.append(check)
            continue
        try:
            result = fn(output, context)
        except Exception as exc:  # never crash the stack; record + move on
            elapsed = int((time.monotonic() - start) * 1000)
            per_check_ms[check] = elapsed
            findings.append({
                "rule": f"{check}.crashed",
                "message": f"{check} check raised: {type(exc).__name__}: {exc}",
                "severity": "error",
                "check": check,
            })
            context.record_verify(VerifyRecord(
                stage=stage, check=check, passed=False,
                findings=[findings[-1]], duration_ms=elapsed,
            ))
            ran.append(check)
            if short_circuit_on_error:
                short_circuited = True
                break
            continue

        elapsed = int((time.monotonic() - start) * 1000)
        per_check_ms[check] = elapsed
        ran.append(check)
        check_findings = result.get("findings") or []
        for f in check_findings:
            f.setdefault("check", check)
            findings.append(f)
        passed = not any((f.get("severity") or "error") == "error" for f in check_findings)
        context.record_verify(VerifyRecord(
            stage=stage, check=check, passed=passed,
            findings=list(check_findings), duration_ms=elapsed,
        ))
        if short_circuit_on_error and not passed:
            short_circuited = True
            break

    passed_all = not any((f.get("severity") or "error") == "error" for f in findings)
    return VerifyReport(
        stage=stage,
        passed=passed_all,
        checks_run=tuple(ran),
        findings=findings,
        per_check_ms=per_check_ms,
        short_circuited=short_circuited,
    )
