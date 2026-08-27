# backend/tests/integration/test_fidelity_loop_e2e.py
"""End-to-end: run FidelityLoopRunner against a fake project with mocked
agents but real patch validation + log-writing."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from services.fidelity_loop import (
    FidelityLoopRunner, PageRef, ProjectContext,
)
from services.vision_evaluator.types import Critique


def _critique(score: float, *, has_high: bool = False) -> Critique:
    return Critique.model_validate({
        "scores": {
            "visualPolish": score, "domainFeel": score, "informationDensity": score,
            "componentCoherence": score, "brandReflection": score,
        },
        "compositeScore": score, "pass": score >= 8 and not has_high,
        "topIssues": [{"severity": "high", "axis": "domainFeel",
                       "nodeIdHint": "hero", "issue": "fake", "suggestion": "fix"}] if has_high else [],
        "strengths": [], "designerApprovalRecommended": False,
    })


@pytest.mark.asyncio
@pytest.mark.integration
async def test_e2e_pages_pass_after_one_patch(tmp_path):
    output_dir = tmp_path / "proj-e2e"
    schemas_dir = output_dir / "src" / "schemas" / "users"
    schemas_dir.mkdir(parents=True)
    schema = {
        "schemaVersion": "2", "id": "users/list", "route": "/users/list",
        "meta": {"title": "Users"}, "dataSources": [],
        "root": {"id": "root", "type": "Stack", "props": {}, "children": []},
    }
    (schemas_dir / "list.json").write_text(json.dumps(schema))

    runner = FidelityLoopRunner(
        output_dir=output_dir,
        project_ctx=ProjectContext(domain="general", app_name="E2E", description="t", tone="neutral"),
    )
    runner.max_iterations = 3

    scores = iter([6.0, 8.5])  # iter 0 fails, iter 1 passes
    with patch("services.fidelity_loop.FIDELITY_LOOP_ENABLED", True), \
         patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"\x89PNG\r\n\x1a\n", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(side_effect=lambda **kw: _critique(next(scores)))), \
         patch("services.fidelity_loop._propose_patches", new=AsyncMock(return_value=[
             {"op": "replace", "path": "/meta/title", "value": "Better Users"}
         ])), \
         patch("services.fidelity_loop._validate_patches", return_value=[]), \
         patch("services.fidelity_loop._apply_patches_transactional",
               side_effect=lambda patches, schema, **kw: {**schema, "meta": {"title": "Better Users"}}):
        report = await runner.run([PageRef(
            short_id="proj-e2e", page_path="users/list", page_route="/users/list", page_type="list"
        )])
    assert report.passed == 1
    assert report.failed == 0

    # Log was written
    log_path = output_dir / "src" / "contracts" / "fidelity-log.json"
    assert log_path.exists()
    log = json.loads(log_path.read_text())
    assert "users/list" in log
    assert log["users/list"]["exit_status"] == "pass"
    assert log["users/list"]["flags"]["fidelity_loop"] is True

    # Schema on disk was updated
    final_schema = json.loads((schemas_dir / "list.json").read_text())
    assert final_schema["meta"]["title"] == "Better Users"

    # iter screenshot was saved
    assert (output_dir / ".fidelity-history" / "users_list" / "iter-0.png").exists()
    assert (output_dir / ".fidelity-history" / "users_list" / "iter-1.png").exists()
