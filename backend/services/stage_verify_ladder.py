"""IRF-M5-T6 wire-up — recover_ladder + verify_stack + domain_conformance.

The three M5 primitives (recover_ladder, verify_stack, domain_conformance)
compose into "run a stage; verify; retry with findings; escalate". This
module owns that composition and the SessionContext bookkeeping that goes
with it. Individual stages call ``run_page_ladder(...)`` and get back a
``LadderResult`` — no per-stage rollout logic to write.

Every attempt appends a ``VerifyRecord`` to ``session_context.current()``
if a context is set, so the acceptance criterion "every stage output logs
a VerifyReport in session_context.verify_history" holds.

Flag: ``FORGE_RECOVER_LADDER`` (default off). When off, ``run_page_ladder``
returns a synthesised single-attempt success wrapping the caller's initial
output — no retries, no verify, but the record is still written so the
verify_history isn't silently empty. This keeps the wire-in additive: a
stage can call it unconditionally without changing generation behavior
until the flag flips.
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict
from typing import Any, Callable

from services.domain_conformance import check_page
from services.recover_ladder import LadderResult, run_ladder
from services.session_context import VerifyRecord, current
from services.stage_check_registry import PAGE_SCHEMA_REGISTRY
from services.verify_stack import CHEAP_CHECKS, run_stack


# ── flag ────────────────────────────────────────────────────────────


def is_enabled() -> bool:
    return os.getenv("FORGE_RECOVER_LADDER", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ── shape adapters ──────────────────────────────────────────────────


def _findings_to_dicts(findings: list) -> list[dict[str, Any]]:
    """Normalise ``shape_profile.Finding`` (or dict) → dicts the
    recover_ladder can consume + the SessionContext can serialise."""
    out: list[dict[str, Any]] = []
    for f in findings or []:
        if isinstance(f, dict):
            out.append(f)
            continue
        # Assume the Finding dataclass shape (rule/message/severity/axis)
        try:
            out.append(asdict(f))
        except Exception:  # noqa: BLE001
            out.append({"message": str(f), "severity": "error"})
    return out


def _record(stage: str, check: str, passed: bool,
            findings: list[dict[str, Any]], duration_ms: int) -> None:
    """Append a VerifyRecord to the ambient SessionContext when present."""
    ctx = current()
    if ctx is None:
        return
    ctx.record_verify(VerifyRecord(
        stage=stage,
        check=check,
        passed=passed,
        findings=findings,
        duration_ms=duration_ms,
    ))


# ── public: run the ladder for a page-schema stage ──────────────────


def run_page_ladder(
    *,
    stage_name: str,
    plan: dict[str, Any],
    route: str,
    attempt_1: Callable[[], Any],
    attempt_2_with_findings: Callable[[list[dict[str, Any]]], Any] | None = None,
    template_fallback: Callable[[], Any] | None = None,
) -> LadderResult:
    """Ladder for stages that emit a page schema.

    ``attempt_1``: produces the page schema dict.
    ``attempt_2_with_findings``: called with the domain_conformance findings
        from attempt_1 when it fails. Skip by passing None (2-rung ladder).
    ``template_fallback``: last-resort emit that's known-safe (deterministic
        builder). Skip by passing None.

    Each attempt's verify pass is ``domain_conformance.check_page(plan, route, schema)``;
    an attempt "passes" when there are no error-severity findings.

    Behavior when the flag is off: ``attempt_1`` runs, verify runs to
    record telemetry, and a ``LadderResult(succeeded=True)`` is
    returned with the attempt_1 output regardless of findings. Retries
    do NOT fire — the caller keeps its historic behavior. This lets you
    wire the ladder into a stage today and flip the flag later.
    """

    def _verify(schema: Any) -> list[dict[str, Any]]:
        if not isinstance(schema, dict):
            return [{"rule": "ladder.non_dict_output",
                     "message": f"stage {stage_name} did not return a dict",
                     "severity": "error"}]
        # IRF-M5-T5 wire: prefer verify_stack.run_stack (records per-check
        # entries in ctx.verify_history) when an ambient SessionContext is
        # available. Falls through to a direct domain_conformance call
        # when no context is set — same historic behavior for callers
        # that don't set one.
        ctx_now = current()
        if ctx_now is not None:
            report = run_stack(
                stage=stage_name,
                output={"plan": plan, "route": route, "schema": schema},
                context=ctx_now,
                checks=tuple(CHEAP_CHECKS),
                check_registry=PAGE_SCHEMA_REGISTRY,
            )
            return list(report.findings)
        findings = check_page(plan, route, schema)
        return _findings_to_dicts(findings)

    # When verify_stack owns the per-check records, the ladder-level
    # aggregate record uses "aggregate" as its check name so
    # verify_history reads as static/structural/domain_conformance +
    # aggregate — no duplicated "domain_conformance" row.
    _aggregate_check = "aggregate" if current() is not None else "domain_conformance"

    if not is_enabled():
        # Record-only mode: run attempt_1, verify for telemetry, always
        # return success with the attempt_1 output.
        started = time.monotonic()
        try:
            output = attempt_1()
            findings = _verify(output)
        except Exception as exc:  # noqa: BLE001
            _record(stage_name, _aggregate_check, False,
                    [{"rule": "attempt.crashed",
                      "message": f"{type(exc).__name__}: {exc}",
                      "severity": "error"}],
                    int((time.monotonic() - started) * 1000))
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        passed = not any(f.get("severity") == "error" for f in findings)
        _record(stage_name, _aggregate_check, passed, findings, duration_ms)
        # Even when findings are non-empty, we return "succeeded" because
        # the flag is off — the caller's historic behavior is preserved.
        return LadderResult(
            succeeded=True, succeeding_rung="llm_first",
            output=output, attempts=[],
        )

    # Flag on: full ladder, retries fire.
    started = time.monotonic()
    result = run_ladder(
        attempt_1=attempt_1,
        attempt_2_with_findings=attempt_2_with_findings,
        verify=_verify,
        template_fallback=template_fallback,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    # One record per attempt so verify_history reflects the full trace.
    for attempt in result.attempts:
        _record(
            f"{stage_name}:{attempt.rung}",
            "domain_conformance",
            attempt.passed,
            attempt.findings,
            duration_ms,  # aggregate — recover_ladder doesn't break out per-rung timing
        )
    return result


__all__ = ["is_enabled", "run_page_ladder"]
