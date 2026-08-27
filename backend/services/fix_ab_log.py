"""Fix-Assistant A/B logging — compare the agentic path vs the single-shot handler.

Every FIX-related assistant turn writes a compact ``fix_ab`` dict into
``Conversation.metadata_``. A separate summarizer walks recent turns for a
project and produces buckets: proposals per mode, approval rate, resolve rate,
average iterations + elapsed time. No PII: the symptom text itself is never
copied — only its length.

Phases recorded:
- ``propose`` — a proposal was emitted (with confidence, artifact kind, seam)
- ``reemit``  — a low-confidence follow-up re-emitted a prior pending proposal
- ``clarify`` — the handler asked a clarifying question, no proposal
- ``error``   — the handler bailed with an error
- ``applied`` — the [APPLY_FIX] chip fired: applied? resolved? committed?

The `mode` field is ``single_shot`` or ``agent`` so we can compare head-to-head
without touching the SSE contract or the frontend.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


# ── entry builders (pure) ─────────────────────────────────────────────────────

_ALLOWED_PHASES = ("propose", "reemit", "clarify", "error", "applied")
_ALLOWED_MODES = ("single_shot", "agent", "unknown")


def build_propose_entry(
    *, mode: str, symptom: str, diagnosis: dict | None,
    trace: Sequence[dict] | None = None, elapsed_ms: int | None = None,
    phase: str = "propose",
) -> dict:
    """The A/B record for a propose or reemit turn.

    `diagnosis` is the emitted `Diagnosis` dict. `trace` (agent-only) is the tool
    call log; iterations is inferred from its length (single-shot = 1).
    """
    diagnosis = diagnosis or {}
    proposed = diagnosis.get("proposedFix") or {}
    artifact = diagnosis.get("artifact") or {}
    tools = [str(t.get("tool")) for t in (trace or []) if isinstance(t, dict) and t.get("tool")]
    iterations = len(tools) if tools else 1
    try:
        confidence = float(diagnosis.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "phase": phase if phase in _ALLOWED_PHASES else "propose",
        "mode": mode if mode in _ALLOWED_MODES else "unknown",
        "symptom_len": len(symptom or ""),
        "outcome": "proposal",
        "confidence": confidence,
        "artifact_kind": artifact.get("kind"),
        "seam": proposed.get("seam"),
        "iterations": iterations,
        "tools_used": tools,
        "elapsed_ms": int(elapsed_ms) if elapsed_ms is not None else None,
    }


def build_clarify_entry(
    *, mode: str, symptom: str, trace: Sequence[dict] | None = None,
    elapsed_ms: int | None = None,
) -> dict:
    tools = [str(t.get("tool")) for t in (trace or []) if isinstance(t, dict) and t.get("tool")]
    return {
        "phase": "clarify",
        "mode": mode if mode in _ALLOWED_MODES else "unknown",
        "symptom_len": len(symptom or ""),
        "outcome": "clarify",
        "confidence": None,
        "artifact_kind": None,
        "seam": None,
        "iterations": len(tools) if tools else 1,
        "tools_used": tools,
        "elapsed_ms": int(elapsed_ms) if elapsed_ms is not None else None,
    }


def build_error_entry(*, mode: str, symptom: str, elapsed_ms: int | None = None) -> dict:
    return {
        "phase": "error",
        "mode": mode if mode in _ALLOWED_MODES else "unknown",
        "symptom_len": len(symptom or ""),
        "outcome": "error",
        "confidence": None,
        "artifact_kind": None,
        "seam": None,
        "iterations": 1,
        "tools_used": [],
        "elapsed_ms": int(elapsed_ms) if elapsed_ms is not None else None,
    }


def build_applied_entry(
    *, mode: str, apply_result: dict | None,
    diagnosis: dict | None = None, elapsed_ms: int | None = None,
) -> dict:
    """A/B record for the [APPLY_FIX] chip. `apply_result` is what
    ``fix_applier.apply_fix`` returned; ``diagnosis`` is the applied Diagnosis
    (so we can attribute the apply outcome to the proposal's mode + seam)."""
    ar = apply_result or {}
    verify = ar.get("verify") or {}
    diagnosis = diagnosis or {}
    proposed = diagnosis.get("proposedFix") or {}
    artifact = diagnosis.get("artifact") or {}
    return {
        "phase": "applied",
        "mode": mode if mode in _ALLOWED_MODES else "unknown",
        "outcome": "applied" if ar.get("applied") else "apply_failed",
        "applied": bool(ar.get("applied")),
        "resolved": bool(verify.get("resolved")),
        "committed": bool(ar.get("committed")),
        "seam": ar.get("seam") or proposed.get("seam"),
        "artifact_kind": artifact.get("kind"),
        "remaining_count": len(verify.get("remaining") or []),
        "elapsed_ms": int(elapsed_ms) if elapsed_ms is not None else None,
    }


# ── summarizer ────────────────────────────────────────────────────────────────

def _iter_entries(conversations: Iterable[Any]):
    """Extract every ``fix_ab`` entry from an iterable of Conversation-shaped
    objects (each with a ``metadata_`` dict). Robust to missing/malformed metadata."""
    for conv in conversations or ():
        md = getattr(conv, "metadata_", None) or (conv.get("metadata_") if isinstance(conv, dict) else None)
        if not isinstance(md, dict):
            continue
        entry = md.get("fix_ab")
        if isinstance(entry, dict):
            yield entry


def _avg(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 2) if xs else None


def summarize(conversations: Iterable[Any]) -> dict:
    """Bucket every recent ``fix_ab`` entry by mode + phase and produce a compact
    summary: counts, approval rate (proposals that led to an apply), resolve rate
    (applies whose verify came back clean), and average iterations + elapsed.

    Deliberately dumb: no time-window filtering, no dedup — callers pass the slice
    they want summarised (e.g. last 200 turns).
    """
    per_mode: dict[str, dict[str, Any]] = {}
    total_by_phase = {p: 0 for p in _ALLOWED_PHASES}

    for e in _iter_entries(conversations):
        mode = e.get("mode") or "unknown"
        phase = e.get("phase") or "propose"
        bucket = per_mode.setdefault(mode, {
            "counts": {p: 0 for p in _ALLOWED_PHASES},
            "_iterations": [], "_elapsed_propose_ms": [], "_confidences": [],
            "_applied_ok": 0, "_apply_total": 0, "_resolved_ok": 0,
            "_seams": {}, "_artifacts": {},
        })
        bucket["counts"][phase] = bucket["counts"].get(phase, 0) + 1
        total_by_phase[phase] = total_by_phase.get(phase, 0) + 1

        if phase in ("propose", "reemit"):
            if isinstance(e.get("iterations"), int):
                bucket["_iterations"].append(e["iterations"])
            if isinstance(e.get("elapsed_ms"), int):
                bucket["_elapsed_propose_ms"].append(e["elapsed_ms"])
            if isinstance(e.get("confidence"), (int, float)):
                bucket["_confidences"].append(float(e["confidence"]))
            seam = e.get("seam")
            if seam:
                bucket["_seams"][seam] = bucket["_seams"].get(seam, 0) + 1
            art = e.get("artifact_kind")
            if art:
                bucket["_artifacts"][art] = bucket["_artifacts"].get(art, 0) + 1

        if phase == "applied":
            bucket["_apply_total"] += 1
            if e.get("applied"):
                bucket["_applied_ok"] += 1
            if e.get("resolved"):
                bucket["_resolved_ok"] += 1

    modes_out: dict[str, dict] = {}
    for mode, b in per_mode.items():
        proposals = b["counts"].get("propose", 0) + b["counts"].get("reemit", 0)
        applies = b["_apply_total"]
        modes_out[mode] = {
            "counts": b["counts"],
            "proposals": proposals,
            "applies": applies,
            "applied_ok": b["_applied_ok"],
            "resolved_ok": b["_resolved_ok"],
            "approval_rate": round(applies / proposals, 3) if proposals else None,
            "resolve_rate": round(b["_resolved_ok"] / applies, 3) if applies else None,
            "avg_iterations": _avg(b["_iterations"]),
            "avg_elapsed_ms": _avg(b["_elapsed_propose_ms"]),
            "avg_confidence": _avg(b["_confidences"]),
            "seams": b["_seams"],
            "artifacts": b["_artifacts"],
        }

    return {
        "modes": modes_out,
        "totals": {"by_phase": total_by_phase, "entries": sum(total_by_phase.values())},
    }
