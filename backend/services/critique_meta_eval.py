# backend/services/critique_meta_eval.py
"""Critique-of-critique sanity pass.

Reads recent fidelity-log entries, samples critiques, and asks a model
'is this critique well-formed and actionable?' to surface degenerate
critique patterns (e.g. evaluator giving 9/10 on every page, or always
flagging the same trivial issue regardless of content).

Run manually as a tuning tool, not in the production loop.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def sample_critiques(output_root: Path, limit: int = 20) -> list[dict[str, Any]]:
    """Sample iter-0 critiques across recent projects."""
    samples: list[dict[str, Any]] = []
    for proj_dir in sorted(output_root.iterdir())[-30:]:  # last ~30 projects
        if not proj_dir.is_dir():
            continue
        log_path = proj_dir / "src" / "contracts" / "fidelity-log.json"
        if not log_path.exists():
            continue
        try:
            log = json.loads(log_path.read_text())
        except json.JSONDecodeError:
            continue
        for page_path, entry in log.items():
            iters = entry.get("iterations", [])
            if iters:
                samples.append({
                    "project": proj_dir.name,
                    "page": page_path,
                    "score": iters[0].get("score"),
                    "issues": iters[0].get("issues", []),
                })
            if len(samples) >= limit:
                return samples
    return samples


def diagnose_distribution(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Quick statistical sanity checks. No LLM call."""
    if not samples:
        return {"sample_size": 0, "warnings": ["no samples available"]}
    scores = [s["score"] for s in samples if s["score"] is not None]
    issue_axes = []
    for s in samples:
        for i in s["issues"]:
            issue_axes.append(i.get("axis", "unknown"))

    warnings: list[str] = []
    if scores:
        avg = sum(scores) / len(scores)
        # Suspicious patterns
        if avg > 9.0:
            warnings.append(f"avg score {avg:.2f} — evaluator may be too lenient")
        if avg < 4.0:
            warnings.append(f"avg score {avg:.2f} — evaluator may be too harsh")
        if max(scores) - min(scores) < 0.5:
            warnings.append(f"score range {min(scores):.2f}–{max(scores):.2f} — evaluator may not be discriminating")
    if issue_axes:
        from collections import Counter
        axis_dist = Counter(issue_axes)
        top_axis, top_count = axis_dist.most_common(1)[0]
        if top_count > len(issue_axes) * 0.7:
            warnings.append(f"{top_axis} flagged in {top_count}/{len(issue_axes)} issues — evaluator may be biased")

    return {
        "sample_size": len(samples),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "score_range": [min(scores), max(scores)] if scores else None,
        "issue_axis_distribution": dict(Counter(issue_axes)) if issue_axes else {},
        "warnings": warnings,
    }
