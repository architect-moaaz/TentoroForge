"""Boot the app, run Playwright, parse results.

The harness assumes the app is already runnable (its dev server can start,
its DB is migrated + seeded). It doesn't try to reset state between runs
yet — the visual-product-search scan flow appends rows rather than
overwrites, so re-running is safe.

Return shape mirrors what the pipeline SSE stream expects: one dict per
journey, plus a top-level aggregate — easy to forward as a `journey_result`
event and easy to reduce to a strict/warn gate decision.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class JourneyResult:
    slug: str
    name: str
    status: str                    # "passed" | "failed" | "timedOut" | "skipped"
    duration_ms: int
    failure: str | None = None
    failing_step: str | None = None  # test.step name that raised
    artifacts: list[str] = field(default_factory=list)  # trace, video, screenshot paths


@dataclass
class SuiteResult:
    ok: bool
    total: int
    passed: int
    failed: int
    duration_ms: int
    journeys: list[JourneyResult] = field(default_factory=list)
    error: str | None = None


def run_journey_suite(
    output_dir: Path | str,
    *,
    base_url: str = "http://localhost:3000",
    boot_check_url: str | None = None,
    boot_timeout_s: int = 30,
    playwright_cwd: Path | str | None = None,
) -> SuiteResult:
    """Execute the emitted journeys against a running app.

    Assumes the app is already listening at `base_url` — the pipeline
    is responsible for bringing it up (via start-all.sh or its own dev
    server). We check reachability then delegate to `npx playwright test`.
    """
    output_dir = Path(output_dir)
    journeys_dir = output_dir / "journeys"
    if not (journeys_dir / "driver.spec.ts").exists():
        return SuiteResult(
            ok=False, total=0, passed=0, failed=0, duration_ms=0,
            error="no driver.spec.ts — emitter didn't run",
        )

    # Boot check: don't waste 90s of Playwright timeout on an app that's
    # not up. A cheap curl-equivalent tells us fast.
    if not _wait_for_boot(boot_check_url or base_url, boot_timeout_s):
        return SuiteResult(
            ok=False, total=0, passed=0, failed=0, duration_ms=0,
            error=f"app not reachable at {base_url} after {boot_timeout_s}s",
        )

    # Playwright runs from the repo root (that's where node_modules lives)
    # but points its config to <app>/journeys. Cleaner than dropping a
    # per-app node_modules symlink.
    cwd = Path(playwright_cwd) if playwright_cwd else Path(__file__).resolve().parents[3]

    started = time.monotonic()
    proc = subprocess.run(
        [
            "npx", "playwright", "test",
            "--config", str(journeys_dir / "playwright.config.ts"),
        ],
        cwd=cwd,
        env={
            **_env(),
            "JOURNEY_BASE_URL": base_url,
        },
        capture_output=True,
        text=True,
        timeout=600,
    )
    duration_ms = int((time.monotonic() - started) * 1000)

    return _parse_results(journeys_dir, duration_ms, proc.stdout, proc.stderr, proc.returncode)


# ── helpers ────────────────────────────────────────────────────────────────

def _env() -> dict[str, str]:
    import os
    return {**os.environ}


def _wait_for_boot(url: str, timeout_s: int) -> bool:
    import urllib.request
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(1)
    # Even a 401/500 counts as reachable — we're testing "app is up", not
    # "app is healthy on the home route". Try once more with the raw
    # socket path.
    from urllib.parse import urlsplit
    from socket import create_connection
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with create_connection((host, port), timeout=2):
            return True
    except Exception:
        return False


def _parse_results(
    journeys_dir: Path,
    duration_ms: int,
    stdout: str,
    stderr: str,
    returncode: int,
) -> SuiteResult:
    """Playwright's JSON reporter writes into `results.json` in the config
    directory. Read that; fall back to stdout parsing if the file's missing
    (usually means Playwright crashed before writing)."""
    results_path = journeys_dir / "results.json"
    if not results_path.exists():
        return SuiteResult(
            ok=False, total=0, passed=0, failed=0, duration_ms=duration_ms,
            error=f"no results.json — playwright likely failed to start.\n"
                  f"stdout tail:\n{stdout[-800:]}\nstderr tail:\n{stderr[-800:]}",
        )

    try:
        report = json.loads(results_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return SuiteResult(
            ok=False, total=0, passed=0, failed=0, duration_ms=duration_ms,
            error=f"results.json unparseable: {exc}",
        )

    journeys: list[JourneyResult] = []
    for suite in report.get("suites", []):
        _walk_suite(suite, journeys)

    passed = sum(1 for j in journeys if j.status == "passed")
    failed = sum(1 for j in journeys if j.status != "passed")
    return SuiteResult(
        ok=(returncode == 0 and failed == 0),
        total=len(journeys),
        passed=passed,
        failed=failed,
        duration_ms=duration_ms,
        journeys=journeys,
    )


def _walk_suite(suite: dict[str, Any], out: list[JourneyResult]) -> None:
    for spec in suite.get("specs", []) or []:
        for t in spec.get("tests", []) or []:
            for r in t.get("results", []) or []:
                title: str = spec.get("title") or "(untitled)"
                slug = title.split("·")[0].strip() if "·" in title else title
                name = title.split("·", 1)[1].strip() if "·" in title else title
                failure = None
                failing_step = None
                if r.get("status") != "passed":
                    errs = r.get("errors") or []
                    if errs:
                        failure = errs[0].get("message") or str(errs[0])
                    # Playwright writes step-level info here — dig for the
                    # innermost failing step so the diagnosis lines up with
                    # the JourneySpec vocabulary, not raw stack frames.
                    for st in _walk_steps(r.get("steps") or []):
                        if st.get("error"):
                            failing_step = st.get("title")
                            break
                artifacts = [
                    a.get("path") for a in (r.get("attachments") or [])
                    if isinstance(a, dict) and a.get("path")
                ]
                out.append(JourneyResult(
                    slug=slug,
                    name=name,
                    status=r.get("status", "unknown"),
                    duration_ms=int(r.get("duration") or 0),
                    failure=failure,
                    failing_step=failing_step,
                    artifacts=artifacts,
                ))
    for child in suite.get("suites", []) or []:
        _walk_suite(child, out)


def _walk_steps(steps: list[dict[str, Any]]):
    for s in steps:
        yield s
        for child in _walk_steps(s.get("steps") or []):
            yield child


def ensure_playwright(cwd: Path) -> bool:
    """Verify Playwright + browser binaries are installed. Cheap check."""
    if not (cwd / "node_modules" / "@playwright" / "test").exists():
        return False
    return shutil.which("npx") is not None
