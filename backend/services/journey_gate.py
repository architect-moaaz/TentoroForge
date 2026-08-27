"""Pipeline seam that runs the journey verifier and emits SSE events.

Wraps ``services.journey_verifier.verify_app`` in the pipeline's event
vocabulary so callers get:

  yield sse_event("status", {"message": "Running journey verification..."})
  yield sse_event("journey_result", {"slug": ..., "status": "passed", ...})
  ...
  yield sse_event("log", {"text": "Journey gate: 1/1 passed in 40s"})

Modes (via ``FORGE_JOURNEY_GATE`` env):

  off   — skip entirely (default; ships without changing existing behavior)
  warn  — run + emit events + log outcome; NEVER blocks the pipeline
  strict— run; raise ``JourneyGateFailure`` if any journey fails

The gate never brings the app up itself — it checks reachability, skips
if the app isn't listening. Booting is the pipeline's job (start-all.sh or
its own dev-server orchestrator); the gate is a post-boot check.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class JourneyGateFailure(Exception):
    """Raised in strict mode when any journey fails."""

    def __init__(
        self,
        summary: str,
        journeys: list[dict[str, Any]],
        hints: list[dict[str, Any]] | None = None,
    ):
        super().__init__(summary)
        self.summary = summary
        self.journeys = journeys
        # Structured remediation hints, one per failed journey. Downstream
        # callers (pipeline, SV harness, Smith) read these to decide
        # whether/how to auto-revise vs. surface to a human.
        self.hints = hints or []


def _mode() -> str:
    """Resolve the pipeline-embedded gate mode.

    Priority:
      1. Explicit ``FORGE_JOURNEY_GATE`` env — off/warn/strict, always wins.
      2. If the master ``FORGE_SELF_VERIFY`` flag is on, default to warn so
         the whole verify surface (chip + build-time gate + on-click
         autofix) is controlled by one switch.
      3. Otherwise off.
    """
    m = (os.environ.get("FORGE_JOURNEY_GATE") or "").strip().lower()
    if m in ("warn", "strict", "off"):
        return m
    # FORGE_QUALITY=full is the one-switch "ship-gate" mode (item 6):
    # journeys must PASS against real data or the build fails — the
    # verification stops being a diagnostic and becomes the gate.
    if (os.environ.get("FORGE_QUALITY") or "").strip().lower() == "full":
        return "strict"
    from services.flag_profile import is_on
    if is_on("FORGE_SELF_VERIFY"):
        return "warn"
    return "off"


async def run_journey_gate(
    output_dir: str | Path,
    *,
    base_url: str = "http://localhost:3000",
    boot_timeout_s: int = 10,
    force_mode: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding SSE-shaped dicts.

    The caller ``yield from`` this from inside its own event stream. On
    strict-mode failure, raises AFTER yielding a final ``journey_gate``
    event with the summary — so the frontend has the diagnosis before the
    stream closes.

    ``force_mode`` — override the env-var gate. User-triggered runs pass
    ``"warn"`` here so they don't require the operator to set a flag; the
    pipeline-embedded gate leaves it as ``None`` so its behaviour stays
    driven by ``FORGE_JOURNEY_GATE``.
    """
    mode = (force_mode or _mode())
    if mode == "off":
        return

    # Imports are lazy so a fresh checkout without pg installed still boots.
    try:
        from services.journey_verifier import verify_app
    except Exception as exc:
        logger.warning("journey_gate: verifier import failed: %s", exc)
        yield _sse("log", {"text": f"[Journey] verifier unavailable: {exc}"})
        return

    yield _sse("status", {"message": "Running journey verification..."})
    yield _sse("office", {
        "type": "agent_start",
        "agent": "journey_verifier",
        "room": "verification",
        "action": f"Walking journeys ({mode} mode)",
    })

    # Boot the app on demand: if it's already listening we use it as-is;
    # otherwise we spawn `npm run dev` in the app dir and kill it on exit.
    # Kept opt-out via FORGE_JOURNEY_BOOT=off so an operator who *wants*
    # the "skip if not reachable" behavior can still get it.
    boot_disabled = (os.environ.get("FORGE_JOURNEY_BOOT") or "").strip().lower() == "off"

    import asyncio
    # JV-15d — prefer container isolation when Docker is available and
    # the app carries the verify artifacts. Falls back to host-mode
    # boot for older generations or environments without Docker.
    try:
        from services.journey_verifier.boot import booted_app, BootError
    except Exception as exc:  # pragma: no cover
        logger.warning("journey_gate: boot module unavailable: %s", exc)
        booted_app = None  # type: ignore[assignment]
        BootError = Exception  # type: ignore[assignment]
    try:
        from services.journey_verifier.container import (
            containerized_app, ContainerBootError, is_available as _docker_ok,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("journey_gate: container module unavailable: %s", exc)
        containerized_app = None  # type: ignore[assignment]
        ContainerBootError = Exception  # type: ignore[assignment]
        _docker_ok = lambda: False  # type: ignore[assignment]

    from pathlib import Path as _Path
    _use_container = (
        containerized_app is not None
        and _docker_ok()
        and (_Path(output_dir) / "docker-compose.verify.yml").exists()
        and (_Path(output_dir) / "Dockerfile.verify").exists()
        and (os.environ.get("FORGE_VERIFY_CONTAINER") or "").lower() != "off"
    )

    def _sync_run() -> Any:
        """Boot (if needed) then verify. Runs on a worker thread because
        Popen + Playwright + urllib are all blocking, and the async gate
        can't be interrupted mid-boot without leaking processes/containers.

        Captures a ``stages`` list of what actually happened so the caller
        can yield descriptive log events after we return — useful when
        container fails and we fall back to host, so the UI's phase pips
        can advance instead of freezing on Kick off.
        """
        stages: list[str] = []
        if _use_container:
            stages.append("container_build_start")
            try:
                with containerized_app(output_dir) as info:
                    stages.append("container_ready")
                    return {
                        "stages": stages,
                        "boot_info": {**info, "booted": True, "mode": "container"},
                        "result": verify_app(
                            output_dir,
                            base_url=info["url"],
                            boot_timeout_s=5,
                        ),
                    }
            except ContainerBootError as exc:
                stages.append(f"container_build_failed:{str(exc)[:200]}")
                logger.warning(
                    "journey_gate: container boot failed, falling back to host: %s",
                    str(exc)[:400],
                )

        if boot_disabled or booted_app is None:
            stages.append("using_existing_app")
            return {
                "stages": stages,
                "boot_info": {"booted": False, "url": base_url, "mode": "existing"},
                "result": verify_app(
                    output_dir, base_url=base_url, boot_timeout_s=boot_timeout_s,
                ),
            }
        stages.append("host_boot_start")
        with booted_app(output_dir, base_url=base_url, boot_timeout_s=90) as info:
            stages.append("host_ready")
            return {
                "stages": stages,
                "boot_info": {**info, "mode": "host"},
                "result": verify_app(
                    output_dir, base_url=base_url, boot_timeout_s=5,
                ),
            }

    # JV-25 — yield an immediate "we're starting boot" log so the frontend
    # progress card can flip from "Kick off" → "Boot container" before the
    # (potentially minute-long) _sync_run returns. Otherwise the pip
    # freezes while we're actually working hard on it.
    if _use_container:
        yield _sse("log", {"text": "[Journey] Building verification container…"})
    else:
        yield _sse("log", {"text": "[Journey] Booting app for verification…"})

    try:
        payload = await asyncio.to_thread(_sync_run)
    except BootError as exc:
        yield _sse("log", {"text": f"[Journey] boot failed: {str(exc)[:400]}"})
        yield _sse("office", {"type": "agent_complete", "agent": "journey_verifier"})
        return

    # JV-25 — narrate the boot journey. Fires descriptive events even
    # when boot ultimately fails, so the UI shows what happened and pips
    # advance past "Kick off" regardless of outcome.
    for stage in payload.get("stages") or []:
        if stage.startswith("container_build_failed:"):
            yield _sse("log", {
                "text": (
                    "[Journey] container build failed, "
                    "falling back to host mode…"
                ),
            })
        elif stage == "host_boot_start":
            yield _sse("log", {"text": "[Journey] booting app in host mode…"})

    boot_info = payload["boot_info"]
    result = payload["result"]
    if boot_info.get("booted"):
        mode = boot_info.get("mode") or "host"
        if mode == "container":
            secs = boot_info.get("boot_seconds", "?")
            proj = boot_info.get("compose_project", "?")
            yield _sse("log", {
                "text": (
                    f"[Journey] booted containerized app at {boot_info['url']} "
                    f"(project={proj}, {secs}s)"
                ),
            })
        else:
            yield _sse("log", {
                "text": f"[Journey] booted app at {boot_info['url']} (pid={boot_info.get('pid')})",
            })

    if result.error:
        # Harness didn't get to run any journeys — app not reachable, no
        # driver emitted, or Playwright crashed before writing results.
        # Never blocking in this branch: a missing runner is a warn-only
        # signal, so a broken CI environment doesn't stop generation.
        yield _sse("log", {
            "text": f"[Journey] gate skipped: {result.error[:200]}",
        })
        yield _sse("office", {"type": "agent_complete", "agent": "journey_verifier"})
        return

    for j in result.journeys:
        yield _sse("journey_result", {
            "slug": j.slug,
            "name": j.name,
            "status": j.status,
            "duration_ms": j.duration_ms,
            "failing_step": j.failing_step,
            "failure": (j.failure or "")[:800],
            # JV-13 — Playwright traces / videos / screenshots. On disk
            # under <app>/journeys/test-results/…; caller decides how to
            # surface them (link vs. download vs. inline preview).
            "artifacts": (j.artifacts or [])[:5],
        })

    summary = (
        f"Journey gate: {result.passed}/{result.total} passed in "
        f"{result.duration_ms // 1000}s"
    )
    yield _sse("log", {"text": f"[Journey] {summary}"})
    yield _sse("journey_gate", {
        "mode": mode,
        "ok": result.ok,
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "duration_ms": result.duration_ms,
    })
    yield _sse("office", {"type": "agent_complete", "agent": "journey_verifier"})

    # Remediation classification — runs in warn AND strict, so a warn-mode
    # generation still emits actionable hints (they just don't stop the
    # pipeline).
    failed_dicts = [
        {
            "slug": j.slug, "name": j.name, "status": j.status,
            "failing_step": j.failing_step, "failure": j.failure,
        }
        for j in result.journeys if j.status != "passed"
    ]
    hints: list[dict[str, Any]] = []
    if failed_dicts:
        try:
            from services.journey_verifier.remediation import build_hints
            hints = [h.to_dict() for h in build_hints(failed_dicts)]
        except Exception as exc:
            logger.warning("journey_gate: remediation classifier failed: %s", exc)

        # Persist a per-app report so an operator (or the SV harness, or
        # Smith) can pick it up out-of-band.
        try:
            import json as _json
            report = {
                "app_slug": Path(output_dir).name,
                "mode": mode,
                "summary": summary,
                "journeys": failed_dicts,
                "hints": hints,
            }
            (Path(output_dir) / "journey-remediation-report.json").write_text(
                _json.dumps(report, indent=2)
            )
        except Exception as exc:
            logger.warning("journey_gate: failed to write remediation report: %s", exc)

        for h in hints:
            yield _sse("journey_remediation", h)

    if mode == "strict" and not result.ok:
        # Convert to a typed exception so the pipeline caller can attribute
        # the failure to this gate specifically (vs. a build error, network
        # blip, etc). Failure list + hints preserved for later revise.
        raise JourneyGateFailure(summary, failed_dicts, hints=hints)


def _sse(event: str, data: Any) -> dict[str, Any]:
    """Match sse_helpers.sse_event's shape without importing it — this
    module has to be import-safe from any pipeline seam, and sse_helpers
    reaches into request context that isn't always present."""
    import json
    return {"event": event, "data": json.dumps(data)}
