"""Verify-trigger hook — Phase 5.2 Playwright loop entry point.

Runs after post_generate_fixes. Reads contracts/proof_report.json; if the
report failed (any error-severity finding survived), dispatches the
existing Playwright verify runner (SV-1..SV-10 infra) to boot the
generated app, run a synthetic user journey per feature × actor, and
attach any runtime errors back to the plan for Smith's fix cycle.

This module is the seam — the runner code itself already exists elsewhere
in the platform (services/verify/). The seam decouples the trigger
condition (proof failed) from the runner implementation so both can
evolve without cross-talk.

Fire-and-forget by design. Runner failures never bubble back to the
pipeline — the fault report on the frontend is the surface.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def should_trigger_verify(output_dir: str | Path) -> bool:
    """True when we should dispatch the Playwright verify loop.

    Rules:
      1. FORGE_VERIFY_AUTO=false → never trigger (opt-out).
      2. No proof_report.json → don't trigger (nothing to verify against).
      3. proof_report.passed=True → don't trigger (nothing to fix).
      4. Otherwise → trigger.
    """
    if os.getenv("FORGE_VERIFY_AUTO") == "false":
        return False
    base = Path(output_dir)
    report_path = base / "contracts" / "proof_report.json"
    if not report_path.exists():
        return False
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    # Explicit True/False in the report. Missing key defaults to False so
    # a malformed/partial report doesn't accidentally skip verification.
    return not bool(data.get("passed", False))


def trigger_verify(output_dir: str | Path, project_id: str | None = None) -> dict:
    """Dispatch the Playwright verify loop for this project.

    Returns a small result dict for the caller to log:
      {"dispatched": bool, "runner": str|None, "reason": str}

    Never raises. The runner lives in services.verify and may or may not
    be reachable in a given environment (e.g. the platform's Playwright
    workers may be down); the trigger records the outcome and returns.
    """
    if not should_trigger_verify(output_dir):
        return {"dispatched": False, "runner": None, "reason": "no-op (skip conditions matched)"}

    # Prefer the existing SV-3/SV-9 runner if it's installed. Try a couple
    # of well-known entry-point locations so the trigger works whether the
    # runner is a module, a class, or a service worker.
    runner_name: str | None = None
    try:
        from services.verify import runner  # type: ignore
        if hasattr(runner, "dispatch_verify_run"):
            runner.dispatch_verify_run(str(output_dir), project_id=project_id)
            runner_name = "services.verify.runner.dispatch_verify_run"
    except Exception as exc:  # noqa: BLE001
        logger.debug("[verify-trigger] runner unavailable: %s", exc)

    if runner_name is None:
        try:
            from services import verify_runner_service as _svc  # type: ignore
            if hasattr(_svc, "trigger"):
                _svc.trigger(str(output_dir), project_id=project_id)
                runner_name = "services.verify_runner_service.trigger"
        except Exception as exc:  # noqa: BLE001
            logger.debug("[verify-trigger] alt runner unavailable: %s", exc)

    if runner_name is None:
        # No runner is installed — leave a breadcrumb so the frontend chip
        # can suggest a next step, but don't block generation.
        _write_pending_marker(output_dir)
        return {
            "dispatched": False,
            "runner": None,
            "reason": "no verify runner installed; pending marker written",
        }

    logger.info(
        "[verify-trigger] dispatched via %s for %s (project_id=%s)",
        runner_name, output_dir, project_id,
    )
    return {"dispatched": True, "runner": runner_name, "reason": "proof failed"}


def _write_pending_marker(output_dir: str | Path) -> None:
    """Persist a small marker file that the frontend chip can read to
    show 'Verify pending — no runner installed'."""
    base = Path(output_dir)
    contracts_dir = base / "contracts"
    try:
        contracts_dir.mkdir(parents=True, exist_ok=True)
        (contracts_dir / "verify_pending.json").write_text(
            json.dumps({"pending": True, "reason": "no runner installed"}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
