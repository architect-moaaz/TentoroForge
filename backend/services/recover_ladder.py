"""Recover ladder — 3-attempt recovery primitive (M5-T6).

Spec P2: every stage output and every Smith tool call gets wrapped in
the same recovery ladder. Cap at 3 attempts. Bounded cost. No
infinite loops.

Ladder:
1. First attempt — LLM-authored change (whatever the caller does).
2. Second attempt — LLM-authored change WITH the verify findings
   pasted into the prompt (DUR-1 pattern, prescriptive errors).
3. Third attempt — deterministic template fallback (caller-supplied).
4. Escalate — surface to user with a structured "here's what I tried"
   report.

The ladder is a pure orchestrator: it doesn't know how to author
changes, doesn't know how to verify. Callers pass in callables for
each: ``attempt_1``, ``attempt_2_with_findings``, ``template_fallback``
(optional), and ``verify``.

Return value tells the caller which rung succeeded and what to hand
to the user if all rungs failed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal


RungName = Literal["llm_first", "llm_with_findings", "template", "escalated"]


AttemptFn = Callable[[], Any]                              # returns output
AttemptWithFindingsFn = Callable[[list[dict[str, Any]]], Any]  # receives prior findings
VerifyFn = Callable[[Any], list[dict[str, Any]]]           # returns findings (empty = pass)


@dataclass
class AttemptRecord:
    """One rung's execution trace — for the escalation report."""
    rung: RungName
    passed: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None  # exception message if the attempt itself crashed


@dataclass
class LadderResult:
    """Outcome of the ladder run."""
    succeeded: bool
    succeeding_rung: RungName | None
    output: Any
    attempts: list[AttemptRecord] = field(default_factory=list)

    def escalation_report(self) -> dict[str, Any]:
        """Structured "here's what I tried" for the user-facing surface.
        Only meaningful when succeeded=False."""
        return {
            "succeeded": self.succeeded,
            "attempts": [
                {
                    "rung": a.rung,
                    "passed": a.passed,
                    "error": a.error,
                    "finding_count": len(a.findings),
                    "sample_findings": a.findings[:3],
                }
                for a in self.attempts
            ],
        }


def run_ladder(
    *,
    attempt_1: AttemptFn,
    attempt_2_with_findings: AttemptWithFindingsFn | None,
    verify: VerifyFn,
    template_fallback: AttemptFn | None = None,
) -> LadderResult:
    """Run the recovery ladder.

    Semantics per rung:
    - ``attempt_1``: call, verify, done if passes.
    - ``attempt_2_with_findings``: call with prior findings, verify.
      Skipped when caller passes None (short 2-rung ladder).
    - ``template_fallback``: call (no findings context — templates
      don't reason about them), verify. Skipped when None.
    - Escalate: no more rungs, return LadderResult with succeeded=False.

    A crashed attempt is recorded (error string) and treated as a
    failed rung — the ladder moves to the next rung. Only completing
    all rungs unsuccessfully results in escalation.
    """
    attempts: list[AttemptRecord] = []

    # Rung 1
    output, record = _try_rung("llm_first", attempt_1, verify)
    attempts.append(record)
    if record.passed:
        return LadderResult(succeeded=True, succeeding_rung="llm_first", output=output, attempts=attempts)

    # Rung 2
    if attempt_2_with_findings is not None:
        prior = record.findings
        output2, record2 = _try_rung(
            "llm_with_findings",
            lambda: attempt_2_with_findings(prior),
            verify,
        )
        attempts.append(record2)
        if record2.passed:
            return LadderResult(succeeded=True, succeeding_rung="llm_with_findings", output=output2, attempts=attempts)

    # Rung 3
    if template_fallback is not None:
        output3, record3 = _try_rung("template", template_fallback, verify)
        attempts.append(record3)
        if record3.passed:
            return LadderResult(succeeded=True, succeeding_rung="template", output=output3, attempts=attempts)

    # Escalate
    attempts.append(AttemptRecord(rung="escalated", passed=False))
    return LadderResult(succeeded=False, succeeding_rung=None, output=None, attempts=attempts)


def _try_rung(rung: RungName, fn: Callable[[], Any], verify: VerifyFn) -> tuple[Any, AttemptRecord]:
    """Execute one rung: call fn, verify, package the record.
    A crash in fn or verify is captured (never re-raised) so the
    ladder can move on."""
    try:
        output = fn()
    except Exception as exc:
        return (None, AttemptRecord(
            rung=rung,
            passed=False,
            findings=[],
            error=f"{type(exc).__name__}: {exc}",
        ))

    try:
        findings = verify(output) or []
    except Exception as exc:
        return (output, AttemptRecord(
            rung=rung,
            passed=False,
            findings=[],
            error=f"verify crashed: {type(exc).__name__}: {exc}",
        ))

    passed = not any((f.get("severity") or "error") == "error" for f in findings)
    return (output, AttemptRecord(rung=rung, passed=passed, findings=list(findings)))
