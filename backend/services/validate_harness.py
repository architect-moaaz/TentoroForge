"""Runtime validation harness (Slice 1 of the validate→repair loop).

Drives the headless click-through crawler (`scripts/crawl.mjs`) against a running
generated app and returns a structured findings report — the ground truth about
whether pages load and buttons work that QA / `next build` cannot see.

Two modes:
  - `base_url` given  → crawl an already-running app (the user ran `./start.sh`);
    this is the primary, testable path.
  - `base_url` None   → boot the app via `./start.sh`, wait until it responds,
    crawl, then tear it down (best-effort; needs Docker + a free :3000).

The route list + admin credentials are read from the generated app itself, so the
crawler needs no configuration. The Playwright layer is verified by running
against a real app; the pure route/parse/summarise logic here is unit-tested.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

_SENTINEL_START = "===FINDINGS==="
_SENTINEL_END = "===END==="
_ROUTE_RE = re.compile(r'"(/[^"]*)":\s*\(\)\s*=>')


def routes_from_registry(app_dir: str | Path) -> list[str]:
    """Extract the route keys the app actually serves from src/schemas/registry.ts."""
    reg = Path(app_dir) / "src" / "schemas" / "registry.ts"
    if not reg.exists():
        return ["/"]
    routes = _ROUTE_RE.findall(reg.read_text(encoding="utf-8"))
    return routes or ["/"]


def parse_crawl_output(stdout: str) -> list[dict]:
    """Pull the findings array out of the crawler's sentinel-delimited JSON block.
    Tolerant of surrounding log noise; returns [] if no valid block is present."""
    if _SENTINEL_START not in stdout:
        return []
    block = stdout.split(_SENTINEL_START, 1)[1]
    block = block.split(_SENTINEL_END, 1)[0].strip()
    try:
        data = json.loads(block)
    except (json.JSONDecodeError, ValueError):
        return []
    findings = data.get("findings") if isinstance(data, dict) else None
    return findings if isinstance(findings, list) else []


def summarize(findings: list[dict]) -> dict:
    """Roll findings up by type for a compact report."""
    by_type: dict[str, int] = {}
    for f in findings:
        t = f.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    return {"total": len(findings), "by_type": by_type, "clean": len(findings) == 0}


def _wait_for_ready(url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status < 500:
                    return True
        except Exception:  # noqa: BLE001 — not up yet
            pass
        time.sleep(2)
    return False


def run_crawl(app_dir: str | Path, base_url: str, node: str = "node") -> dict:
    """Run the Playwright crawler against a running app; return the findings report."""
    from services.post_gen_actions import admin_credentials

    creds = admin_credentials(app_dir)
    cfg = {
        "baseUrl": base_url.rstrip("/"),
        "routes": routes_from_registry(app_dir),
        "email": creds["email"],
        "password": creds["password"],
    }
    script = Path(__file__).resolve().parents[1] / "scripts" / "crawl.mjs"
    try:
        proc = subprocess.run(
            [node, str(script), json.dumps(cfg)],
            cwd=str(app_dir), capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "node not found", "findings": []}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "crawl timed out", "findings": []}
    findings = parse_crawl_output(proc.stdout)
    unavailable = any(f.get("type") == "harness_unavailable" for f in findings)
    return {
        "ok": not unavailable,
        "error": "playwright unavailable" if unavailable else None,
        "findings": [f for f in findings if f.get("type") != "harness_unavailable"],
        "summary": summarize([f for f in findings if f.get("type") != "harness_unavailable"]),
        "base_url": cfg["baseUrl"],
        "routes_crawled": len(cfg["routes"]),
    }


def run_validation(app_dir: str | Path, base_url: str | None = None,
                   boot_timeout: float = 180.0) -> dict:
    """Validate a generated app. With `base_url`, crawl the running app. Without,
    boot it via ./start.sh, wait until ready, crawl, then tear down."""
    app_dir = Path(app_dir)
    if base_url:
        return run_crawl(app_dir, base_url)

    start = app_dir / "start.sh"
    if not start.exists():
        return {"ok": False, "error": "no start.sh (cannot boot app)", "findings": []}
    proc = None
    try:
        proc = subprocess.Popen(["bash", str(start)], cwd=str(app_dir),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if not _wait_for_ready("http://localhost:3000", boot_timeout):
            return {"ok": False, "error": "app did not become ready in time", "findings": []}
        return run_crawl(app_dir, "http://localhost:3000")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()
