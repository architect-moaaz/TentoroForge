"""IRF M7-T3 — write one substrate-brief row per generation.

Reads the finished plan and post-gen artifacts, distills the four-axis
substrate summary + observability metrics, and appends one JSONL line to
``logs/substrate_briefs/YYYY-MM-DD.jsonl`` (env-overridable).

Consumed by ``backend/routers/quality.py`` → the /quality dashboard.

Never raises: any failure is logged and swallowed so a broken brief
never blocks a generation.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LOG_DIR = "logs/substrate_briefs"


def _log_dir() -> Path:
    return Path(os.environ.get("FORGE_SUBSTRATE_LOG_DIR", _DEFAULT_LOG_DIR))


def _read_plan(output_dir: Path) -> dict[str, Any]:
    # Canonical location in generated apps is src/contracts/plan.json; the
    # other two are historical fallbacks (contracts/ from earlier layouts,
    # bare plan.json for tests + synthetic fixtures).
    for cand in (
        output_dir / "src" / "contracts" / "plan.json",
        output_dir / "contracts" / "plan.json",
        output_dir / "plan.json",
    ):
        if cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                return {}
    return {}


def _coverage_verdict_status(plan: dict, override: str | None) -> str:
    if isinstance(override, str) and override:
        return override
    cv = plan.get("coverage_verdict")
    if isinstance(cv, dict):
        s = cv.get("status")
        if isinstance(s, str) and s:
            return s
    if isinstance(cv, str) and cv:
        return cv
    return "in_scope"


def _archetype_names(plan: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for a in (plan.get("archetypes") or []):
        if isinstance(a, dict):
            name = a.get("recipe") or a.get("name")
            if isinstance(name, str):
                out.append(name)
    return out


def _read_critic_score(output_dir: Path) -> float | None:
    """Average score from reports/page-critic/*.json (excluding summary)."""
    critic_dir = output_dir / "reports" / "page-critic"
    if not critic_dir.is_dir():
        return None
    scores: list[float] = []
    for f in critic_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        s = data.get("score")
        if isinstance(s, (int, float)):
            scores.append(float(s))
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)


def emit_brief(
    output_dir: str | Path,
    *,
    project_id: str | None = None,
    guards_fired: list[str] | None = None,
    aesthetic_profile: str | None = None,
    coverage_verdict: str | None = None,
) -> Path | None:
    """Append one substrate-brief JSONL row for this generation.

    Returns the path written to, or None on any failure.
    """
    try:
        root = Path(output_dir)
        plan = _read_plan(root)
        row: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "output_dir": str(root),
            "app_shape": plan.get("app_shape") or {},
            "archetypes": _archetype_names(plan),
            "industry": plan.get("industry"),
            "runtime_context": plan.get("runtime_context") or [],
            "coverage_verdict": _coverage_verdict_status(plan, coverage_verdict),
            "aesthetic_profile": aesthetic_profile,
            "guards_fired": list(guards_fired or []),
            "design_critic_score": _read_critic_score(root),
            # Reserved for future writers (Smith outcomes, manual-patch tally):
            "manual_patches": 0,
            "smith_turn_success": {"success": 0, "total": 0},
        }
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        target = log_dir / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl"
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return target
    except Exception as exc:  # noqa: BLE001
        logger.warning("substrate_brief_writer: emit failed: %s", exc)
        return None
