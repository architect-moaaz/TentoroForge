"""Unified ship verdict (V3) — one report, one verdict, per build.

Verification evidence today is scattered across a dozen artifacts
(delivery-report, binding-smoke, workflow_validation, security-report,
quarantine, requirement-fidelity, the emitted in-app test manifest…). Each
is authoritative for its own dimension but nothing answers the only question
that matters at the end of a build: **can this app ship?**

``build_ship_report(output_dir)`` folds every known verification artifact
into ``<output_dir>/ship-report.json``:

    {
      "verdict": "pass" | "warn" | "block",
      "summary": {"errors": n, "warnings": n, "criticals": n},
      "sources": {
         "<name>": {"present": bool, "errors": n, "warnings": n,
                     "criticals": n, "sample": [up to 5 clipped items]},
      },
      "generated_at": iso8601,
    }

Verdict policy (FORGE_SHIP_GATE: off | warn (default) | strict):
  * any CRITICAL finding (security secrets/anon-read class) → "block"
  * errors > 0 → "warn"  ("block" instead when FORGE_SHIP_GATE=strict —
    the one-switch ship-gate mode, matching FORGE_QUALITY=full intent)
  * otherwise → "pass"

Purely file-driven and tolerant: absent artifacts are reported as absent,
never invented; malformed ones count as a warning on the report itself.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPORT_NAME = "ship-report.json"
_SAMPLE_LIMIT = 5
_CLIP = 240

# source name → candidate relative paths (first hit wins)
_SOURCES: dict[str, tuple[str, ...]] = {
    "delivery": ("contracts/delivery-report.json",),
    "security": ("security-report.json",),
    "quarantine": ("src/contracts/quarantine.json", "contracts/quarantine.json"),
    "binding_smoke": ("contracts/binding-smoke.json",),
    "binding_report": ("binding-report.json",),
    "workflow_validation": ("contracts/workflow_validation.json",),
    "requirement_fidelity": ("contracts/requirement-fidelity.json",),
    "proof": ("contracts/proof_report.json",),
    "app_tests": ("src/__tests__/generated/manifest.json",),
    "auto_heal": ("contracts/auto_heal_report.json",),
}

# keys that carry finding lists in the various artifacts, by severity bucket
_ERROR_KEYS = ("errors", "faults", "failures", "missing", "unresolved")
_WARNING_KEYS = ("warnings", "issues", "gaps")


def _clip(item: Any) -> Any:
    s = item if isinstance(item, str) else json.dumps(item, default=str)
    return s[:_CLIP]


def _severity_of(item: Any) -> str:
    if isinstance(item, dict):
        sev = str(item.get("severity") or item.get("level") or "").lower()
        if sev == "critical":
            return "critical"
    return "error"


def _walk_findings(doc: Any) -> tuple[list, list, list]:
    """Collect (criticals, errors, warnings) from an artifact of unknown but
    conventional shape — finding lists under well-known keys, including one
    level of nesting (e.g. quarantine entries carrying `unresolved`)."""
    criticals: list = []
    errors: list = []
    warnings: list = []

    def _visit(node: Any, depth: int) -> None:
        if depth > 3 or not isinstance(node, dict):
            return
        for key, value in node.items():
            if not isinstance(value, list):
                if isinstance(value, dict):
                    _visit(value, depth + 1)
                continue
            lk = key.lower()
            if lk in _ERROR_KEYS:
                for item in value:
                    (criticals if _severity_of(item) == "critical" else errors).append(item)
            elif lk in _WARNING_KEYS:
                warnings.extend(value)
            elif lk == "quarantine":
                for entry in value:
                    if isinstance(entry, dict):
                        _visit(entry, depth + 1)
    _visit(doc, 0)
    return criticals, errors, warnings


def _load_source(output_dir: Path, rel_paths: tuple[str, ...]) -> tuple[dict | None, str | None]:
    for rel in rel_paths:
        p = output_dir / rel
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")), rel
            except Exception as exc:  # noqa: BLE001
                return {"warnings": [f"unparseable artifact {rel}: {exc}"]}, rel
    return None, None


def _gate_mode() -> str:
    raw = (os.environ.get("FORGE_SHIP_GATE") or "warn").strip().lower()
    return raw if raw in ("off", "warn", "strict") else "warn"


def build_ship_report(output_dir: str) -> dict:
    """Fold all verification artifacts into one verdict; write + return it."""
    root = Path(output_dir)
    sources: dict[str, dict] = {}
    total_crit = total_err = total_warn = 0

    for name, rel_paths in _SOURCES.items():
        doc, found_rel = _load_source(root, rel_paths)
        if doc is None:
            sources[name] = {"present": False, "errors": 0, "warnings": 0, "criticals": 0}
            continue
        crit, errs, warns = _walk_findings(doc)
        total_crit += len(crit)
        total_err += len(errs)
        total_warn += len(warns)
        sources[name] = {
            "present": True,
            "path": found_rel,
            "criticals": len(crit),
            "errors": len(errs),
            "warnings": len(warns),
            "sample": [_clip(i) for i in (crit + errs + warns)[:_SAMPLE_LIMIT]],
        }

    mode = _gate_mode()
    if total_crit > 0 and mode != "off":
        verdict = "block"
    elif total_err > 0 or total_crit > 0:
        verdict = "block" if mode == "strict" else "warn"
    else:
        verdict = "pass"

    report = {
        "verdict": verdict,
        "mode": mode,
        "summary": {"criticals": total_crit, "errors": total_err, "warnings": total_warn},
        "sources": sources,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        (root / REPORT_NAME).write_text(json.dumps(report, indent=2, default=str),
                                        encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.exception("[ship-report] persist failed")
    return report
