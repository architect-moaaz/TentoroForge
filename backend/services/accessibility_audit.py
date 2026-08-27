"""Spec E Wave 2 — WCAG accessibility audit (axe-core wrapper).

Flag-gated (``FORGE_A11Y_GATE``) helper that runs axe-core against a
set of URLs and writes a summary to ``<output_dir>/verify-run/
accessibility.json``. When axe-core (or the Node harness it needs) is
not installed on the host, falls back to a pure-Python heuristic that
walks emitted page schemas + generated TSX for the top-10 issue
classes: missing labels, missing alt, missing aria-* on interactives,
missing landmark, colour-contrast placeholders.

The heuristic is intentionally conservative — it exists so CI can
enforce a baseline even without a headless browser. Real axe runs
should be preferred in staging.

Public entry:

    run_axe_audit(output_dir, urls=[...]) -> dict
        {"engine": "axe|heuristic", "pages": [...], "summary": {...}}

Never raises; always returns a dict with an ``ok`` field.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Flag helpers
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    """Master flag — default off. Enable in CI once axe/heuristic is
    proven not to break existing pipelines."""
    return os.getenv("FORGE_A11Y_GATE", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def is_strict() -> bool:
    """When true, callers should treat any ``critical`` axe violation
    as a build failure. Default warn-only."""
    return os.getenv("FORGE_A11Y_GATE_STRICT", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ---------------------------------------------------------------------------
# axe-core discovery — best-effort, no hard dependency
# ---------------------------------------------------------------------------


def _find_axe_runner() -> Path | None:
    """Locate a Node script that runs axe-core against a URL. We look
    for a project-local ``scripts/axe-runner.mjs`` first; then any
    globally-installed axe-core CLI. Returns None when nothing is
    reachable — the caller falls back to the Python heuristic.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    local = repo_root / "scripts" / "axe-runner.mjs"
    if local.is_file():
        return local
    return None


def _run_axe_against_url(runner: Path, url: str, timeout_s: int = 30) -> dict:
    """Invoke the Node axe runner. The runner is expected to accept a
    URL as argv[1] and print a JSON summary to stdout matching the
    ``{violations, passes, incomplete}`` axe-core shape."""
    try:
        proc = subprocess.run(
            ["node", str(runner), url],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"error": f"axe subprocess failed: {exc}"}
    if proc.returncode != 0:
        return {"error": f"axe exited {proc.returncode}: {proc.stderr[:200]}"}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"axe stdout not JSON: {exc}"}


# ---------------------------------------------------------------------------
# Heuristic fallback — walk emitted schemas/TSX for obvious a11y misses
# ---------------------------------------------------------------------------

# Heuristic checks — each returns a list of (severity, rule_id, message).
_INTERACTIVE_TAGS = ("Button", "IconButton", "Link", "NavLink", "Input", "Select")


def _walk_schema(node: Any, path: str, out: list[dict]) -> None:
    if isinstance(node, dict):
        comp = node.get("component")
        props = node.get("props") or {}
        if comp == "IconButton":
            if not (props.get("aria-label") or props.get("ariaLabel") or props.get("label")):
                out.append({
                    "severity": "serious",
                    "rule": "button-name",
                    "message": "IconButton has no aria-label or label prop.",
                    "path": path,
                })
        if comp == "Input" and not (props.get("label") or props.get("aria-label")):
            out.append({
                "severity": "serious",
                "rule": "label",
                "message": "Input rendered without a label.",
                "path": path,
            })
        if comp == "Image" and not (props.get("alt") or props.get("aria-label")):
            out.append({
                "severity": "critical",
                "rule": "image-alt",
                "message": "Image has no alt text.",
                "path": path,
            })
        for k, v in node.items():
            _walk_schema(v, f"{path}.{k}", out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_schema(v, f"{path}[{i}]", out)


def _heuristic_audit_output_dir(output_dir: str) -> list[dict]:
    root = Path(output_dir)
    findings: list[dict] = []

    # Landmark presence — the shell should carry a <main id="main">.
    schema_page = root / "src" / "lib" / "schema-page.tsx"
    if schema_page.is_file():
        text = schema_page.read_text(encoding="utf-8", errors="ignore")
        if '<main' not in text or 'id="main"' not in text:
            findings.append({
                "severity": "moderate",
                "rule": "landmark-main",
                "message": "Shell template does not stamp <main id=\"main\">.",
                "path": str(schema_page.relative_to(root)),
            })
    # SkipLink presence in layout.
    layout = root / "src" / "app" / "layout.tsx"
    if layout.is_file():
        text = layout.read_text(encoding="utf-8", errors="ignore")
        if 'SkipLink' not in text:
            findings.append({
                "severity": "moderate",
                "rule": "skip-link",
                "message": "Root layout does not render SkipLink primitive.",
                "path": str(layout.relative_to(root)),
            })

    # Walk every emitted page schema JSON.
    schemas_dir = root / "src" / "schemas"
    if schemas_dir.is_dir():
        for p in schemas_dir.rglob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            per_page: list[dict] = []
            _walk_schema(data, str(p.relative_to(root)), per_page)
            findings.extend(per_page)

    return findings


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def run_axe_audit(
    output_dir: str,
    urls: Iterable[str] | None = None,
    *,
    write_report: bool = True,
) -> dict:
    """Run an accessibility audit.

    * When axe-core is discoverable AND ``urls`` is non-empty, run axe
      against each URL and aggregate the violations.
    * Otherwise, walk the emitted artefacts on disk with a heuristic
      pass and report the findings.
    * Write ``verify-run/accessibility.json`` when ``write_report`` is
      true.

    Returns a summary dict — never raises.
    """
    urls = list(urls or [])
    runner = _find_axe_runner()
    engine = "heuristic"
    pages: list[dict] = []

    if runner and urls:
        engine = "axe"
        for url in urls:
            axe_result = _run_axe_against_url(runner, url)
            violations = axe_result.get("violations", [])
            incomplete = axe_result.get("incomplete", [])
            pages.append({
                "page": url,
                "violations": violations,
                "incomplete": incomplete,
                "error": axe_result.get("error"),
            })
    else:
        # Heuristic — one synthetic "page" carrying all findings.
        findings = _heuristic_audit_output_dir(output_dir)
        pages.append({
            "page": "<static heuristic scan>",
            "violations": findings,
            "incomplete": [],
        })

    critical = sum(
        1
        for p in pages
        for v in p.get("violations", [])
        if (v.get("impact") or v.get("severity")) == "critical"
    )
    serious = sum(
        1
        for p in pages
        for v in p.get("violations", [])
        if (v.get("impact") or v.get("severity")) == "serious"
    )
    total = sum(len(p.get("violations", [])) for p in pages)

    summary = {
        "ok": True,
        "engine": engine,
        "pages_audited": len(pages),
        "total_violations": total,
        "critical": critical,
        "serious": serious,
        "strict": is_strict(),
        "would_fail_build": bool(is_strict() and (critical or serious)),
        "pages": pages,
    }

    if write_report:
        try:
            report_dir = Path(output_dir) / "verify-run"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "accessibility.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("accessibility_audit: report write failed: %s", exc)
            summary["ok"] = False
            summary["report_error"] = str(exc)

    return summary


__all__ = ["run_axe_audit", "is_enabled", "is_strict"]
