"""Sprint 10 — Critic summary rollup.

Sprints 3/6/7/8 each drop a per-page report in
``<output>/reports/page-critic/<slug>.json``. Individually they're
noise; together they're the honest quality signal we've been missing —
pass rate, average score, which signature moves the LLM keeps skipping,
which pages carry the brand and which don't.

This module walks that directory at the end of a generation and writes
``<output>/reports/page-critic/summary.json`` — one file the pipeline
report + Smith + humans can all read.

Best-effort. If no per-page reports exist, ``build_summary`` returns
``None`` (no summary file gets written). Never raises on malformed input.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPORTS_DIRNAME = "reports/page-critic"
_SUMMARY_NAME = "summary.json"
_LEDGER_NAME = "_memory.json"  # from Sprint 9 — skipped when aggregating


def _iter_report_files(reports_dir: Path):
    """Yield each per-page report path (skip the memory ledger + summary
    itself so we don't recursively aggregate our own output)."""
    if not reports_dir.exists():
        return
    skip = {_SUMMARY_NAME, _LEDGER_NAME}
    for p in sorted(reports_dir.glob("*.json")):
        if p.name in skip:
            continue
        yield p


def _load_report(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        logger.warning("[critic-summary] skipping unreadable %s", path)
        return None


def build_summary(output_dir: str) -> dict | None:
    """Aggregate every per-page critic report into a single summary dict.

    Returns ``None`` when there are no per-page reports to aggregate —
    that's the normal case on a run without the critic enabled, and we
    intentionally don't leave behind an empty summary file.
    """
    reports_dir = Path(output_dir) / _REPORTS_DIRNAME
    reports: list[dict] = []
    for p in _iter_report_files(reports_dir):
        r = _load_report(p)
        if r is not None:
            reports.append({"slug": p.stem, **r})

    if not reports:
        return None

    total = len(reports)
    passed = sum(1 for r in reports if bool(r.get("passes")))
    scores = [
        s for r in reports
        if isinstance(s := r.get("score"), (int, float))
    ]
    avg_score = round(sum(scores) / len(scores), 2) if scores else None

    # Which signature moves are the LLM most reliably skipping? Count the
    # `missing` slots from every page's signature-moves detector output.
    missing_moves: Counter[str] = Counter()
    moves_applied: Counter[str] = Counter()
    brand_totals: list[int] = []
    brand_meets = 0
    brand_evaluated = 0
    for r in reports:
        det = r.get("_detectors") or {}
        sig = det.get("signature_moves") or {}
        for m in sig.get("missing") or []:
            missing_moves[str(m)] += 1
        for m in sig.get("detected") or []:
            moves_applied[str(m)] += 1
        brand = det.get("brand_echo") or {}
        if brand.get("primary_hex"):
            brand_evaluated += 1
            brand_totals.append(int(brand.get("total_echoes") or 0))
            if brand.get("meets_minimum"):
                brand_meets += 1

    # Severity-tagged gap counts across the whole run — a cheap read of
    # "how often did HIGH-sev gaps escalate a page to failing?"
    gap_severity: Counter[str] = Counter()
    for r in reports:
        for g in r.get("gaps") or []:
            sev = str(g.get("severity") or "unknown").lower()
            gap_severity[sev] += 1

    summary: dict[str, Any] = {
        "total_pages":            total,
        "pages_passed":           passed,
        "pages_failed":           total - passed,
        "pass_rate":              round(passed / total, 3) if total else None,
        "avg_score":              avg_score,
        "gap_counts_by_severity": dict(gap_severity),
        "signature_moves": {
            "top_missing":  missing_moves.most_common(10),
            "top_applied":  moves_applied.most_common(10),
        },
        "brand_echo": {
            "pages_evaluated": brand_evaluated,
            "pages_meets_min": brand_meets,
            "avg_echoes":      (
                round(sum(brand_totals) / len(brand_totals), 2)
                if brand_totals else None
            ),
        },
        "pages": [
            {
                "slug":   r.get("slug"),
                "score":  r.get("score"),
                "passes": bool(r.get("passes")),
                "gaps":   len(r.get("gaps") or []),
            }
            for r in reports
        ],
    }
    return summary


def persist_summary(output_dir: str) -> Path | None:
    """Build and write the summary. Returns the written path, or None
    when there was nothing to aggregate / on write failure."""
    try:
        summary = build_summary(output_dir)
        if summary is None:
            return None
        reports_dir = Path(output_dir) / _REPORTS_DIRNAME
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / _SUMMARY_NAME
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        logger.exception(
            "[critic-summary] persist_summary failed for %s", output_dir,
        )
        return None


__all__ = ["build_summary", "persist_summary"]
