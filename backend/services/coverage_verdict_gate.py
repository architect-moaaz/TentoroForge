"""Coverage-verdict gate — first stage of the pipeline once the planner
has emitted a plan.

Pure decision function: reads ``plan.coverage_verdict`` and returns a
:class:`GateDecision` telling the caller what to do next. Never mutates
the plan; never writes files; never fires side effects. Caller in
``_run_relay_pipeline`` decides whether to proceed, log the gap, or
halt+surface the refusal card.

See docs/superpowers/specs/2026-08-11-intelligent-rich-forge.md
"P1 → Coverage verdicts" and the plan's IRF-M2-T1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


GateAction = Literal["proceed", "proceed_and_log_gap", "halt"]


@dataclass(frozen=True)
class GateDecision:
    """Outcome of the coverage-verdict gate.

    Fields:
    - ``action``: what the caller should do — proceed / proceed and log
      a gap-log entry / halt with a refusal card.
    - ``verdict_status``: the raw status string from the plan (for
      logging + telemetry).
    - ``reason``: one-sentence human-facing explanation from the
      planner.
    - ``nearest_supported``: the "adjacent thing Forge can build"
      string when the pipeline halts (surface on the refusal card).
    - ``missing_dimensions``: the axes/dimensions the planner marked
      as missing (used to compose the gap-log entry).
    - ``suggested_extensions``: concrete substrate additions the
      planner proposed (also for the gap-log entry).
    - ``gap_log_entry``: fully-formed dict ready to hand to
      ``substrate_gap_log.append(entry)`` when action is
      ``proceed_and_log_gap`` (None otherwise).
    - ``refusal_payload``: fully-formed dict ready to attach to the
      SSE ``coverage_verdict`` event when action is ``halt`` (None
      otherwise).
    """
    action: GateAction
    verdict_status: str
    reason: str
    nearest_supported: str | None = None
    missing_dimensions: tuple[str, ...] = ()
    suggested_extensions: tuple[str, ...] = ()
    gap_log_entry: dict[str, Any] | None = None
    refusal_payload: dict[str, Any] | None = None


def evaluate(plan: dict[str, Any], *, brief_summary: str = "", gen_slug: str = "") -> GateDecision:
    """Read ``plan.coverage_verdict`` and return the gate decision.

    Missing / malformed verdict is treated as ``in_scope`` — this
    module has to be **tolerant during rollout** because M1-T1 (planner
    emission) lands after M2. Once the planner reliably emits, the
    plan validator (services.shape_profile.validate_coverage_verdict)
    is what enforces presence; this gate never re-validates because
    that would double-report the same finding.

    ``brief_summary`` and ``gen_slug`` are optional identifiers that
    show up in the gap-log entry / refusal payload for downstream
    consumers.
    """
    verdict = plan.get("coverage_verdict") or {}
    if not isinstance(verdict, dict):
        verdict = {}

    status = str(verdict.get("status") or "in_scope")
    reason = str(verdict.get("reason") or "")
    nearest = verdict.get("nearest_supported")
    if nearest is not None:
        nearest = str(nearest)
    missing = tuple(str(x) for x in (verdict.get("missing_dimensions") or []))
    suggested = tuple(str(x) for x in (verdict.get("suggested_extensions") or []))

    if status == "out_of_scope":
        return GateDecision(
            action="halt",
            verdict_status=status,
            reason=reason,
            nearest_supported=nearest,
            missing_dimensions=missing,
            suggested_extensions=suggested,
            refusal_payload={
                "status": "out_of_scope",
                "reason": reason,
                "nearest_supported": nearest,
                # Frontend renders three actions:
                # generate_nearest, refine_brief, cancel.
                "actions": [
                    {"id": "generate_nearest", "label": f"Generate {nearest}" if nearest else "Generate nearest"},
                    {"id": "refine_brief", "label": "Refine my brief"},
                    {"id": "cancel", "label": "Cancel"},
                ],
            },
        )

    if status == "extension_needed":
        return GateDecision(
            action="proceed_and_log_gap",
            verdict_status=status,
            reason=reason,
            nearest_supported=nearest,
            missing_dimensions=missing,
            suggested_extensions=suggested,
            gap_log_entry={
                "gen_slug": gen_slug,
                "brief_summary": brief_summary,
                "reason": reason,
                "missing_dimensions": list(missing),
                "suggested_extensions": list(suggested),
                "nearest_supported": nearest,
            },
        )

    # in_scope OR unknown status (tolerant fallback)
    return GateDecision(
        action="proceed",
        verdict_status=status if status == "in_scope" else "in_scope",
        reason=reason,
    )
