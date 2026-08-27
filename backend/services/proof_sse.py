"""SSE payload builder for the proof_pass report — Phase 5.1 UX piece.

The proof_pass writes contracts/proof_report.json. Callers emit its
contents as a `proof_result` SSE event so the frontend chip on the
project card can render live pass/fail + a click-to-inspect list of
findings. This module handles the "read + shape for SSE" plumbing so
the router just does:

    from services.proof_sse import build_proof_sse_payload
    payload = build_proof_sse_payload(output_dir)
    if payload is not None:
        yield sse_event("proof_result", payload)

`build_proof_sse_payload` returns None when no proof_report was written
(the deterministic modules were disabled or the pipeline crashed before
the proof pass ran) — the caller should skip emitting the event in
that case rather than sending a null payload.
"""
from __future__ import annotations

import json
from pathlib import Path

# Frontend chip caps how many findings it shows inline before offering a
# "view all" link. Match that here so the payload stays small.
_MAX_INLINE_FINDINGS = 25


def build_proof_sse_payload(output_dir: str | Path) -> dict | None:
    """Read contracts/proof_report.json and format it for SSE emission.

    Returns None if the file is missing, malformed, or the callers should
    otherwise skip the event.
    """
    base = Path(output_dir)
    path = base / "contracts" / "proof_report.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    findings = data.get("findings") or []
    if not isinstance(findings, list):
        findings = []

    # Sort ship-blockers first so the chip UI shows what breaks the app
    # before what's merely noisy.
    def _severity_rank(f):
        return 0 if isinstance(f, dict) and f.get("severity") == "error" else 1
    findings_sorted = sorted(findings, key=_severity_rank)
    inline = findings_sorted[:_MAX_INLINE_FINDINGS]
    truncated = max(0, len(findings_sorted) - _MAX_INLINE_FINDINGS)

    return {
        "passed": bool(data.get("passed", False)),
        "error_count": int(data.get("error_count") or 0),
        "warning_count": int(data.get("warning_count") or 0),
        "findings": inline,
        "truncated": truncated,
        "report_path": "contracts/proof_report.json",
    }
