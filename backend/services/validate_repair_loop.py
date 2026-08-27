"""Slice 3 of the validate→repair loop: validate → repair → re-validate until the
app is clean (or no progress / max rounds). This is the engine behind the chat's
"Test, Validate & Repair" action.

`validate(app_dir) -> list[findings]` and `repair(app_dir, findings) -> {made_progress,...}`
are injected so the control logic (converge / thrash-guard / round cap) is testable
without a browser; `run_validate_repair` wires the real harness + dispatcher.
"""
from __future__ import annotations


def _signature(findings: list[dict]) -> frozenset:
    """Stable identity of a finding set — to detect a stuck (non-converging) loop."""
    return frozenset(
        (f.get("type"), f.get("route"), f.get("buttonLabel") or f.get("detail"))
        for f in (findings or [])
    )


def _summarize(findings: list[dict]) -> dict:
    by_type: dict[str, int] = {}
    for f in findings or []:
        by_type[f.get("type", "unknown")] = by_type.get(f.get("type", "unknown"), 0) + 1
    return {"total": len(findings or []), "by_type": by_type}


def validate_and_repair(app_dir, *, validate, repair, max_rounds: int = 3) -> dict:
    """Loop validate→repair until clean, stuck, or `max_rounds` reached.

    Stops when: no findings (clean), the repair made no progress, the finding set
    is identical to the previous round (thrash), or the round cap is hit."""
    rounds: list[dict] = []
    prev_sig: frozenset | None = None
    findings: list[dict] = []
    stop = "max_rounds"

    for i in range(max_rounds):
        findings = validate(app_dir) or []
        sig = _signature(findings)
        rounds.append({"round": i + 1, "findings": _summarize(findings)})

        if not findings:
            stop = "clean"
            break
        if sig == prev_sig:
            stop = "no_change"
            break
        result = repair(app_dir, findings) or {}
        if not result.get("made_progress"):
            stop = "no_progress"
            break
        prev_sig = sig

    return {
        "clean": len(findings) == 0,
        "stopped": stop,
        "rounds": rounds,
        "remaining": _summarize(findings),
        "remaining_findings": findings,
    }


def run_validate_repair(app_dir, *, base_url: str | None = None, max_rounds: int = 3,
                        fix_agent=None) -> dict:
    """Real wiring: crawl the running app (or boot it), route findings through the
    deterministic guards + optional fix agent, and re-validate."""
    from services.validate_harness import run_validation
    from services.repair_dispatcher import dispatch_repairs

    def _validate(d):
        res = run_validation(d, base_url=base_url)
        if not res.get("ok") and res.get("error"):
            # Harness unavailable / boot failed — surface as a single finding so the
            # loop stops cleanly rather than churning.
            return [{"type": "harness_error", "detail": res["error"]}]
        return res.get("findings", [])

    def _repair(d, findings):
        return dispatch_repairs(d, findings, fix_agent=fix_agent)

    return validate_and_repair(app_dir, validate=_validate, repair=_repair, max_rounds=max_rounds)
