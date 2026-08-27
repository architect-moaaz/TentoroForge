# backend/routers/_debug_fidelity.py
"""Debug endpoint: render + score a single page; append to fidelity log.

Phase-13 wiring — single-shot, no loop. Designer triggers it manually via
this endpoint or via the editor's CritiquePanel "regenerate with critique"
button (later)."""
from __future__ import annotations

import base64
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

from config import FIDELITY_SCORING_ENABLED, FIDELITY_STATS_ENABLED, RENDER_SERVICE_URL
from services.fidelity_log import append_fidelity_entry, read_fidelity_log
from services.vision_evaluator import EvaluatorContext, evaluate_page


router = APIRouter()


def _output_dir(short_id: str) -> Path:
    return Path(__file__).resolve().parent.parent.parent / "output" / short_id


@router.post("/api/_debug/score-page/{short_id}")
async def score_page(
    short_id: str,
    page_route: str,
    page_path: str,
    domain: str = "general",
    app_name: str = "App",
    description: str = "",
    tone: str = "professional",
):
    """Render the page, score it, append to fidelity-log.json. Returns the
    structured critique."""
    if not FIDELITY_SCORING_ENABLED:
        raise HTTPException(403, "Fidelity scoring disabled (set FIDELITY_SCORING_ENABLED=true)")

    output_dir = _output_dir(short_id)
    if not output_dir.exists():
        raise HTTPException(404, f"project {short_id} not found")

    # 1. Render via render-service
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(
                f"{RENDER_SERVICE_URL}/render",
                json={"projectId": short_id, "pageRoute": page_route, "viewport": "desktop"},
            )
        except httpx.RequestError as e:
            raise HTTPException(503, f"render-service unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    render = r.json()

    # 2. Decode PNG + a11y tree
    png_bytes = base64.b64decode(render["pngBase64"])
    a11y_tree = render.get("accessibilityTree", "")

    # 3. Score via vision evaluator
    ctx = EvaluatorContext(
        domain=domain, app_name=app_name, description=description, tone=tone,
        route=page_route, page_type=page_path.split("/")[-1] if "/" in page_path else "page",
        page_role=f"users navigate to {page_route}",
        iteration=0, max_iter=1,
    )
    critique = await evaluate_page(png_bytes=png_bytes, a11y_tree=a11y_tree, ctx=ctx)

    # 4. Append to fidelity log
    # Determine the next iter number for manual re-score: continue from the last
    # logged iter, mark this one as manual_run.
    existing = read_fidelity_log(str(output_dir))
    existing_entry = existing.get(page_path, {})
    existing_iters = existing_entry.get("iterations", [])
    next_iter = (existing_entry.get("final_iteration", -1) + 1) if existing_iters else 0

    append_fidelity_entry(
        output_dir=str(output_dir),
        page_path=page_path,
        score=critique.compositeScore,
        issues=[i.model_dump() for i in critique.topIssues],
        iteration=next_iter,
        passed=critique.pass_,
        manual_run=True,
    )

    return critique.model_dump(by_alias=True)


@router.get("/api/_debug/fidelity-stats")
async def fidelity_stats(since: str | None = None):
    """Aggregate per-project fidelity-log.json across recent generations."""
    if not FIDELITY_STATS_ENABLED:
        raise HTTPException(403, "Fidelity stats endpoint disabled (set FIDELITY_STATS_ENABLED=true)")

    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    if not output_root.exists():
        return {"projects": 0, "pages_scored": 0}

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"invalid since: {since!r}; use ISO 8601")

    projects = 0
    pages_scored = 0
    score_total = 0.0
    iter_total = 0
    pass_count = 0
    cap_exhausted = 0
    cost_total = 0.0
    iter_dist = Counter()

    for proj_dir in output_root.iterdir():
        if not proj_dir.is_dir():
            continue
        log_path = proj_dir / "src" / "contracts" / "fidelity-log.json"
        if not log_path.exists():
            continue
        if since_dt and datetime.fromtimestamp(log_path.stat().st_mtime).astimezone() < since_dt.astimezone():
            continue
        try:
            log = json.loads(log_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not log:
            continue
        projects += 1
        for page_path, entry in log.items():
            iters = entry.get("iterations", [])
            if not iters:
                continue
            pages_scored += 1
            score_total += float(entry.get("final_score", 0.0))
            iter_total += entry.get("final_iteration", 0)
            iter_dist[entry.get("final_iteration", 0)] += 1
            cost_total += float(entry.get("cost_usd", 0.0))
            if entry.get("exit_status") == "pass":
                pass_count += 1
            if entry.get("exit_status") == "budget":
                cap_exhausted += 1

    avg_score = round(score_total / pages_scored, 2) if pages_scored else 0.0
    avg_iters = round(iter_total / pages_scored, 2) if pages_scored else 0.0
    pass_rate = round(pass_count / pages_scored, 2) if pages_scored else 0.0
    avg_cost = round(cost_total / projects, 2) if projects else 0.0
    return {
        "projects": projects,
        "pages_scored": pages_scored,
        "pass_rate": pass_rate,
        "avg_iters": avg_iters,
        "median_score": avg_score,  # using avg as proxy; median requires extra pass
        "avg_cost_usd": avg_cost,
        "cap_exhausted": cap_exhausted,
        "iter_distribution": dict(iter_dist),
    }


@router.get("/api/_debug/fidelity-log/{short_id}")
async def get_fidelity_log(short_id: str):
    """Return the raw fidelity-log.json for a given project short_id."""
    output_dir = _output_dir(short_id)
    log_path = output_dir / "src" / "contracts" / "fidelity-log.json"
    if not log_path.exists():
        return {}
    try:
        return json.loads(log_path.read_text())
    except json.JSONDecodeError:
        raise HTTPException(500, "fidelity log is corrupted")


from services.critique_meta_eval import sample_critiques, diagnose_distribution


@router.get("/api/_debug/critique-meta-eval")
async def critique_meta_eval(limit: int = 20):
    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    samples = sample_critiques(output_root, limit=limit)
    return diagnose_distribution(samples)


from services.bank_promotion import find_candidates


@router.get("/api/_debug/bank-candidates")
async def bank_candidates_list():
    """List schemas eligible for promotion into the reference bank.
    Manual review step — does NOT promote automatically."""
    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    return {"candidates": find_candidates(output_root)}
