"""Reframe helper (IRF-M2-T5, backend service).

Pure function the eventual ``POST /api/projects/{id}/reframe``
endpoint will call. The endpoint itself needs auth + project-scope
wiring that couples to the router layer — deferring that to when
the frontend OutOfScopeCard (M2-T4) needs it. The service is
usable today from Smith tools or an internal admin script.

Given a plan whose coverage_verdict is ``out_of_scope``, this
helper rewrites the plan to target the ``nearest_supported``
adjacent app — the user's "Generate nearest supported instead"
choice on the OutOfScopeCard.

The rewrite is minimal and structural:
- Replace the app description/brief with the ``nearest_supported``
  string (planner will regenerate axes from that).
- Clear ``coverage_verdict`` so the next planner run re-emits it.
- Add ``plan.reframe_history`` audit entry for traceability.

The next call to ``_ensure_normalized_plan`` (which runs
``enrich_plan``) will fill in the four axes from the new brief.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def reframe_from_verdict(plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rewrite ``plan`` in place-safe manner (returns fresh dict) so
    the next generation targets ``coverage_verdict.nearest_supported``.

    Returns ``(reframed_plan, report)`` where report describes what
    was rewritten. Raises ``ReframeError`` when the plan has no
    out_of_scope verdict — nothing to reframe.
    """
    if not isinstance(plan, dict):
        raise ReframeError("plan is not a dict")
    verdict = plan.get("coverage_verdict") or {}
    if not isinstance(verdict, dict):
        raise ReframeError("plan.coverage_verdict missing or malformed")
    if verdict.get("status") != "out_of_scope":
        raise ReframeError(
            f"reframe only applies to out_of_scope verdicts; got status="
            f"{verdict.get('status')!r}"
        )
    nearest = verdict.get("nearest_supported")
    if not nearest or not isinstance(nearest, str):
        raise ReframeError("verdict missing nearest_supported")

    original_brief = str(
        plan.get("description") or plan.get("brief") or plan.get("prompt") or ""
    )

    new_plan = _deep_copy(plan)
    new_brief = (
        f"{nearest}\n\n"
        f"(Reframed from an out-of-scope request. Original brief: "
        f"{original_brief[:300]!r}. Reason for reframe: "
        f"{verdict.get('reason', '') or 'out_of_scope'})"
    )
    new_plan["description"] = new_brief
    if "brief" in new_plan:
        new_plan["brief"] = new_brief

    # Clear the verdict so the next planner run re-emits it. Keep the
    # other axes as hints — the planner will re-evaluate them against
    # the new brief and either keep, adjust, or overwrite.
    new_plan.pop("coverage_verdict", None)

    # Audit trail
    history = new_plan.setdefault("reframe_history", [])
    if isinstance(history, list):
        history.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "from_status": verdict.get("status"),
            "reason": verdict.get("reason"),
            "nearest_supported": nearest,
            "original_brief_snippet": original_brief[:300],
        })

    return (new_plan, {
        "reframed_to": nearest,
        "original_brief_snippet": original_brief[:300],
        "reframe_history_length": len(new_plan.get("reframe_history") or []),
    })


class ReframeError(ValueError):
    """Raised when a plan cannot be reframed."""


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value
