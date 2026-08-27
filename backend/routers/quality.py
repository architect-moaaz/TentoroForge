"""Quality dashboard metrics endpoint (IRF M7-T3).

Reads:
- backend/logs/substrate_briefs/*.jsonl — per-generation substrate summary
  (produced by generate.py; one JSON per line: {ts, project_id,
   app_shape, archetypes, industry, runtime_context, coverage_verdict,
   guards_fired[], design_critic_score, smith_turn_success, ...})

Returns a single flat JSON payload the /quality page renders. No auth
gate — it's an internal dashboard mounted at localhost:6501/quality.
The endpoint is defensive: missing logs directory returns an empty
payload instead of 500 so the page renders on a fresh checkout.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/quality", tags=["quality"])

# Log location — relative to backend/ working dir.
_LOG_DIR = Path(os.environ.get("FORGE_SUBSTRATE_LOG_DIR", "logs/substrate_briefs"))
_LOOKBACK_ROWS = int(os.environ.get("FORGE_QUALITY_LOOKBACK", "500"))


def _iter_brief_rows(root: Path, limit: int) -> list[dict[str, Any]]:
    if not root.exists() or not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for jsonl in sorted(root.glob("*.jsonl"), reverse=True):
        try:
            with jsonl.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                    if len(rows) >= limit:
                        return rows
        except OSError:
            continue
    return rows


def _bucket_by_shape(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Average design-critic score per app_shape.label."""
    sums: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        label = ((r.get("app_shape") or {}).get("label")) or "unknown"
        score = r.get("design_critic_score")
        if isinstance(score, (int, float)):
            sums[label].append(float(score))
    return {
        label: {
            "avg_score": round(sum(vals) / len(vals), 1),
            "count": len(vals),
        }
        for label, vals in sums.items()
    }


def _rate(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return round(numer / denom * 100.0, 1)


def _shape_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    verdicts = Counter((r.get("coverage_verdict") or "unknown") for r in rows)
    guards: Counter[str] = Counter()
    manual_patches: list[int] = []
    smith_success = 0
    smith_total = 0
    for r in rows:
        for g in (r.get("guards_fired") or []):
            if isinstance(g, str):
                guards[g] += 1
        mp = r.get("manual_patches")
        if isinstance(mp, int):
            manual_patches.append(mp)
        st = r.get("smith_turn_success")
        if isinstance(st, dict):
            smith_success += int(st.get("success") or 0)
            smith_total += int(st.get("total") or 0)

    avg_manual = round(sum(manual_patches) / len(manual_patches), 2) if manual_patches else 0.0
    return {
        "total_generations": total,
        "coverage": {
            "in_scope": verdicts.get("in_scope", 0),
            "extension_needed": verdicts.get("extension_needed", 0),
            "out_of_scope": verdicts.get("out_of_scope", 0),
            "unknown": verdicts.get("unknown", 0),
            "extension_needed_rate_pct": _rate(verdicts.get("extension_needed", 0), total),
        },
        "guards_fired_top": guards.most_common(10),
        "manual_patches_per_gen_avg": avg_manual,
        "smith_turn_success_pct": _rate(smith_success, smith_total),
    }


@router.get("/metrics")
async def quality_metrics() -> dict[str, Any]:
    rows = _iter_brief_rows(_LOG_DIR, _LOOKBACK_ROWS)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "log_dir": str(_LOG_DIR),
        "lookback_rows": _LOOKBACK_ROWS,
        "row_count": len(rows),
        "summary": _shape_summary(rows),
        "design_critic_by_shape": _bucket_by_shape(rows),
    }
