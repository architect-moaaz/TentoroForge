# backend/tests/services/test_fidelity_loop.py
"""FidelityLoopRunner tests — uses heavy mocking since the runner integrates
the patch agent, render service, vision evaluator, and disk I/O."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.fidelity_loop import (
    FidelityLoopRunner, PageRef, PageOutcome, FidelityReport, ProjectContext,
)
from services.vision_evaluator.types import Critique


def _make_critique(score: float, *, has_high: bool = False) -> Critique:
    issues = []
    if has_high:
        issues.append({
            "severity": "high", "axis": "domainFeel", "nodeIdHint": "hero",
            "issue": "fake high-severity issue", "suggestion": "fix it",
        })
    return Critique.model_validate({
        "scores": {
            "visualPolish": score, "domainFeel": score, "informationDensity": score,
            "componentCoherence": score, "brandReflection": score,
        },
        "compositeScore": score,
        "pass": score >= 8.0 and not has_high,
        "topIssues": issues, "strengths": [],
        "designerApprovalRecommended": False,
    })


def _make_runner(tmp_path: Path) -> FidelityLoopRunner:
    output_dir = tmp_path / "proj"
    (output_dir / "src" / "schemas" / "users").mkdir(parents=True)
    schema = {
        "schemaVersion": "2", "id": "users/list", "route": "/users",
        "meta": {"title": "Users"}, "dataSources": [],
        "root": {"id": "root", "type": "Stack", "props": {}, "children": []},
    }
    (output_dir / "src" / "schemas" / "users" / "list.json").write_text(json.dumps(schema), encoding="utf-8")
    return FidelityLoopRunner(
        output_dir=output_dir,
        project_ctx=ProjectContext(domain="general", app_name="Test", description="t", tone="neutral"),
    )


def _make_page() -> PageRef:
    return PageRef(short_id="proj", page_path="users/list", page_route="/users/list", page_type="list")


# ---- Test 1: pass at iter 0 (no patches needed) ----
@pytest.mark.asyncio
async def test_passes_at_iter_0(tmp_path):
    runner = _make_runner(tmp_path)
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(return_value=_make_critique(8.5))):
        outcome = await runner._run_one_page(_make_page())
    assert outcome.passed is True
    assert outcome.exit_status == "pass"
    assert len(outcome.iterations) == 1
    assert outcome.iterations[0].iter == 0


# ---- Test 2: passes at iter 1 after one patch ----
@pytest.mark.asyncio
async def test_patches_then_passes(tmp_path):
    runner = _make_runner(tmp_path)
    scores = iter([6.0, 8.4])
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(side_effect=lambda **kw: _make_critique(next(scores), has_high=(kw.get("ctx", None) and False)))), \
         patch("services.fidelity_loop._propose_patches", new=AsyncMock(return_value=[
             {"op": "replace", "path": "/meta/title", "value": "Patients"}
         ])), \
         patch("services.fidelity_loop._validate_patches", return_value=[]), \
         patch("services.fidelity_loop._apply_patches_transactional", side_effect=lambda patches, schema, **kw: {**schema, "meta": {"title": "Patients"}}):
        outcome = await runner._run_one_page(_make_page())
    assert outcome.passed is True
    assert outcome.exit_status == "pass"
    assert len(outcome.iterations) == 2
    assert outcome.iterations[0].iter == 0
    assert outcome.iterations[1].iter == 1


# ---- Test 3: hits max_iterations without passing → failed_fidelity ----
@pytest.mark.asyncio
async def test_exhausts_iterations_failed_fidelity(tmp_path):
    runner = _make_runner(tmp_path)
    runner.max_iterations = 3
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(return_value=_make_critique(6.0, has_high=True))), \
         patch("services.fidelity_loop._propose_patches", new=AsyncMock(return_value=[
             {"op": "replace", "path": "/meta/title", "value": "X"}
         ])), \
         patch("services.fidelity_loop._validate_patches", return_value=[]), \
         patch("services.fidelity_loop._apply_patches_transactional", side_effect=lambda patches, schema, **kw: schema), \
         patch("services.fidelity_loop._reprompt_schema_agent", new=AsyncMock(return_value=None)):
        outcome = await runner._run_one_page(_make_page())
    assert outcome.passed is False
    assert outcome.failed_fidelity is True


# ---- Test 4: plateau exit ----
@pytest.mark.asyncio
async def test_plateau_exit(tmp_path):
    runner = _make_runner(tmp_path)
    scores = iter([6.0, 7.5, 7.55, 7.55])  # plateau between iter 1 and iter 2
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(side_effect=lambda **kw: _make_critique(next(scores), has_high=True))), \
         patch("services.fidelity_loop._propose_patches", new=AsyncMock(return_value=[
             {"op": "replace", "path": "/meta/title", "value": "X"}
         ])), \
         patch("services.fidelity_loop._validate_patches", return_value=[]), \
         patch("services.fidelity_loop._apply_patches_transactional", side_effect=lambda patches, schema, **kw: schema):
        outcome = await runner._run_one_page(_make_page())
    assert outcome.exit_status == "plateau"


# ---- Test 5: regression rolls back, marks regressed iter ----
@pytest.mark.asyncio
async def test_regression_rolls_back(tmp_path):
    runner = _make_runner(tmp_path)
    scores = iter([7.5, 5.0, 5.0])  # iter 0=7.5, iter 1=5.0 (regression, rejected), iter 2=5.0 plateau
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(side_effect=lambda **kw: _make_critique(next(scores), has_high=True))), \
         patch("services.fidelity_loop._propose_patches", new=AsyncMock(return_value=[
             {"op": "replace", "path": "/meta/title", "value": "X"}
         ])), \
         patch("services.fidelity_loop._validate_patches", return_value=[]), \
         patch("services.fidelity_loop._apply_patches_transactional", side_effect=lambda patches, schema, **kw: schema):
        outcome = await runner._run_one_page(_make_page())
    # The regressed iter should be in the log
    assert any(it.status == "regressed" for it in outcome.iterations)


# ---- Test 6: concurrent run dispatches all pages ----
@pytest.mark.asyncio
async def test_run_processes_multiple_pages_in_parallel(tmp_path):
    runner = _make_runner(tmp_path)
    runner.concurrency = 2
    pages = [PageRef(short_id="proj", page_path=f"p/{i}", page_route=f"/p/{i}", page_type="list") for i in range(3)]
    with patch("services.fidelity_loop.FIDELITY_LOOP_ENABLED", True), \
         patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(return_value=_make_critique(8.5))), \
         patch.object(runner, "_run_one_page", new=AsyncMock(side_effect=lambda p: PageOutcome(
             page=p, final_score=8.5, passed=True, iterations=[],
             exit_status="pass", failed_fidelity=False, wall_clock_ms=10, cost_usd=0.01))):
        report = await runner.run(pages)
    assert len(report.outcomes) == 3
    assert report.passed == 3
