"""Format a VerifyRun into rich prose Smith can read on subsequent turns.

The router previously persisted a fixed "Kicking off..." message when the
user triggered a verify pass, and nothing when it finished. That left
Smith blind about faults / hints on the very next turn.

This module produces two payloads:
  - ``format_verify_summary(row)`` → a Markdown-ish string suitable for
    persisting as an assistant chat message. Smith sees this via
    ``load_chat_history_for_prompt`` from then on.
  - ``format_verify_report_json(row)`` → the same data as a compact dict,
    used by the ``read_last_verify_run`` Smith tool.

Both are pure — take a VerifyRun row (or a dict), return text/dict. No
DB access here.
"""
from __future__ import annotations

from typing import Any


def format_verify_summary(row: Any) -> str:
    """Human-readable + Smith-readable summary of a completed VerifyRun.

    The message intentionally names each failed journey + its fix hint so
    Smith can quote specifics ("the workflow-definition hint said…") on
    later turns without having to call the read tool.
    """
    d = _row_to_dict(row)
    status = d.get("status") or "unknown"
    passed = d.get("interactions_passed") or 0
    total = d.get("interactions_run") or 0
    faults = d.get("faults_count") or 0
    rounds = d.get("rounds_run") or 1

    parts: list[str] = []

    if status == "failed":
        parts.append(f"Verify run **failed to complete**: {d.get('error') or 'no details'}.")
        return "\n".join(parts)

    # Header: interaction pass. JV-17 — when the runner sidecar wasn't
    # reachable (typical on local dev) we record `interaction_pass.skipped`
    # and short-circuit interactions_passed=0. Report that honestly instead
    # of "0/N passed", which reads like N failures.
    interaction_pass = (d.get("report") or {}).get("interaction_pass") or {}
    if interaction_pass.get("skipped"):
        reason = interaction_pass.get("reason") or "runner unavailable"
        parts.append(
            f"Verified the app: **interaction pass skipped** ({reason})."
        )
    elif total:
        head = f"Verified the app: **{passed}/{total} interactions passed**"
        if faults:
            head += f", {faults} fault(s) found"
            if rounds > 1:
                head += f" (Smith ran {rounds} fix round(s))"
        else:
            head += " — no faults."
        parts.append(head + ".")
    else:
        parts.append("Verify ran but reported no interaction totals.")

    # Journey block
    journey = (d.get("report") or {}).get("journey")
    if journey:
        parts.append("")
        parts.append(_format_journey(journey))

    # Fault list (SV report side)
    faults_list = (d.get("report") or {}).get("faults") or []
    if faults_list:
        parts.append("")
        parts.append(_format_faults(faults_list))

    return "\n".join(p for p in parts if p is not None)


def format_verify_report_json(
    row: Any,
    *,
    top_n: int = 10,
) -> dict[str, Any]:
    """Compact structured view of the last run for tool consumption.

    Capped by default: at most ``top_n`` faults, ``top_n`` hints per
    journey walk, ``top_n`` per-journey results, so a large run doesn't
    blow Smith's context. ``has_more`` flags tell Smith when there is
    additional detail available (pass a larger ``top_n`` to retrieve).

    Failure messages are also clipped per row (400 chars each) — the
    full trace text is on disk if a human needs it.
    """
    top_n = max(1, min(top_n, 40))  # hard clamp
    d = _row_to_dict(row)
    report = d.get("report") or {}
    journey = report.get("journey") or {}
    first = journey.get("first_run") or {}
    second = journey.get("second_run") or {}
    autofix = journey.get("autofix") or {}

    def _cap_results(rows: list) -> tuple[list, bool]:
        if not rows:
            return [], False
        capped = [
            {**r, "failure": (r.get("failure") or "")[:400]}
            for r in rows[:top_n]
        ]
        return capped, len(rows) > top_n

    def _cap(rows: list) -> tuple[list, bool]:
        if not rows:
            return [], False
        return rows[:top_n], len(rows) > top_n

    all_faults = report.get("faults") or []
    faults, faults_more = _cap(all_faults)

    def _walk(walk: dict) -> dict:
        results, results_more = _cap_results(walk.get("results") or [])
        hints, hints_more = _cap(walk.get("hints") or [])
        return {
            "summary": walk.get("gate_summary"),
            "results": results,
            "hints": hints,
            "has_more": {"results": results_more, "hints": hints_more},
        }

    # SV-STRICT-3b: attach the narrated payload if the pipeline stashed
    # one on row.report["narrated"]. Kept optional — legacy runs (or a
    # pass where narration failed) simply omit the key.
    narrated = report.get("narrated") or {}

    return {
        "run_id": str(d.get("id") or ""),
        "status": d.get("status"),
        "error": d.get("error"),
        "interactions": {
            "run": d.get("interactions_run"),
            "passed": d.get("interactions_passed"),
            "faults_count": d.get("faults_count"),
            "rounds_run": d.get("rounds_run"),
        },
        "faults": faults,
        "faults_has_more": faults_more,
        "narrated": narrated,
        "journey": {
            "first_run": _walk(first),
            "autofix": autofix,
            "second_run": _walk(second) if second else None,
        },
        "_pagination": {"top_n": top_n, "max_top_n": 40},
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: Any) -> dict[str, Any]:
    """Accept a SQLAlchemy row OR a dict. Handy for tests + future-proofing
    (some callers pass the plain dict returned by ``run_self_verify``)."""
    if isinstance(row, dict):
        return row
    # SQLAlchemy model — read attrs by name.
    keys = (
        "id", "status", "error",
        "interactions_run", "interactions_passed",
        "faults_count", "rounds_run", "report",
    )
    return {k: getattr(row, k, None) for k in keys}


def _format_journey(journey: dict[str, Any]) -> str:
    """Journey subsection of the summary — first walk, autofix, re-walk."""
    lines: list[str] = ["**Journey walk (real-browser click-through):**"]
    first = journey.get("first_run") or {}
    first_summary = first.get("gate_summary")
    if first_summary:
        p = first_summary.get("passed") or 0
        t = first_summary.get("total") or 0
        f = first_summary.get("failed") or 0
        lines.append(f"- First run: {p}/{t} passed, {f} failed.")
    hints = first.get("hints") or []
    results = first.get("results") or []
    artifacts_by_slug = {
        r.get("slug"): r.get("artifacts") or []
        for r in results if r.get("status") != "passed"
    }
    if hints:
        lines.append("- Fix hints per failed journey:")
        for h in hints[:10]:
            seam = h.get("target_seam") or "unknown"
            slug = h.get("journey_slug") or "?"
            cause = h.get("likely_cause") or ""
            step = h.get("failing_step") or "?"
            lines.append(f"  - **{slug}** ({seam}) — failed at *{step}*: {cause}")
            arts = artifacts_by_slug.get(slug) or []
            if arts:
                # Show first 2 artifact paths — user can inspect trace
                # locally. Playwright's trace viewer opens .zip files.
                lines.append(f"    - trace/screenshot: {', '.join(arts[:2])}")

    autofix = journey.get("autofix")
    if autofix:
        dispatched = autofix.get("dispatched") or []
        skipped = autofix.get("skipped_seams") or []
        if dispatched:
            # Include per-seam summary line so Smith sees which specific
            # fixer ran (e.g. orphan_wiring_pass) not just the seam label.
            for d in dispatched:
                seam = d.get("seam") or "?"
                summ = d.get("summary") or ""
                ok = d.get("ok", True)
                marker = "" if ok else " (failed)"
                lines.append(f"- Auto-fix `{seam}`{marker}: {summ}")
        if skipped:
            lines.append(f"- Skipped seams (no handler): {', '.join(skipped)}.")

    second = journey.get("second_run") or {}
    second_summary = second.get("gate_summary")
    if second_summary:
        p = second_summary.get("passed") or 0
        t = second_summary.get("total") or 0
        f = second_summary.get("failed") or 0
        verdict = "clean" if f == 0 else "still failing"
        lines.append(f"- Second run after auto-fix: {p}/{t} passed ({verdict}).")

    return "\n".join(lines)


def _format_faults(faults: list[dict[str, Any]]) -> str:
    """Render the runner faults list.

    Accepts BOTH shapes:
      • Test/legacy shape: ``{route, classification, summary}`` — flat keys.
      • Live runner shape (JV-27/A2): ``{interaction:{id,...}, evidence:{
        stack_trace, body_excerpt, status,...}, passed, flaky}`` — nested.

    Before A2 this function read the flat keys only, so every real-runner
    fault came out as ``? — unclassified:``. Now we probe the nested shape
    first, fall back to flat, and derive a classification from the stack
    trace when the runner didn't set one.
    """
    lines = ["**Runner faults (first 5):**"]
    for f in faults[:5]:
        interaction = f.get("interaction") or {}
        evidence = f.get("evidence") or {}

        # Label: prefer the interaction id (e.g. `form:/admin/[id]/edit`),
        # then the interaction's route, then any flat route/path key.
        label = (
            interaction.get("id")
            or interaction.get("route")
            or f.get("route")
            or f.get("path")
            or "?"
        )

        # Classification: use whatever the runner/classifier stamped, else
        # derive from the stack trace prefix. V&F 2.0 (M1) adds a
        # `class_name` field emitted by the new fault_classifier — prefer
        # it when present so the chip label matches what the dispatcher
        # actually did with the fault (e.g. `db-schema-mismatch` rather
        # than `server-error`).
        classification = (
            f.get("class_name")
            or f.get("signature")
            or f.get("classification")
            or f.get("kind")
        )
        stack = evidence.get("stack_trace") or ""
        if not classification:
            classification = _classify_from_stack(stack) or "unclassified"

        # Description: first non-empty line of stack_trace / body_excerpt /
        # legacy summary/message, trimmed to 200 chars.
        raw = (
            (stack.splitlines()[0].strip() if stack else "")
            or evidence.get("body_excerpt")
            or f.get("summary")
            or f.get("message")
            or ""
        )
        desc = raw.strip()[:200]
        lines.append(f"- *{label}* — {classification}: {desc}")
    if len(faults) > 5:
        lines.append(f"- (+{len(faults) - 5} more; call `read_last_verify_run` for full detail.)")
    return "\n".join(lines)


def _classify_from_stack(stack: str) -> str | None:
    """Best-effort classification from a stack-trace prefix when the
    runner didn't send one. Keep the set small and specific — anything
    unrecognized falls through to `unclassified` upstream."""
    if not stack:
        return None
    s = stack.lower()
    if "err_name_not_resolved" in s or "dns" in s:
        return "network-error"
    if "err_connection_refused" in s or "econnrefused" in s:
        return "network-error"
    if "timeout" in s or "timed out" in s:
        return "timeout"
    if "500" in s.split("\n", 1)[0]:
        return "server-error"
    return "runtime"
