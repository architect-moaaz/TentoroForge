# backend/tests/services/test_bank_promotion.py
import json
from pathlib import Path

import pytest

from services.bank_promotion import find_candidates, promote_candidate


def _make_project(root: Path, project_id: str, register: str, domain: str,
                   page_path: str, score: float, has_high: bool = False):
    proj = root / project_id
    proj.mkdir(parents=True)
    (proj / "src" / "contracts").mkdir(parents=True)
    (proj / "src" / "contracts" / "design-spec.json").write_text(
        json.dumps({"register": register, "domain": domain})
    )
    issues = [{"severity": "high"}] if has_high else []
    (proj / "src" / "contracts" / "fidelity-log.json").write_text(json.dumps({
        page_path: {
            "final_score": score,
            "iterations": [{"score": score, "issues": issues, "pass": score >= 8.5}],
        }
    }), encoding="utf-8")
    schema_dir = proj / "src" / "schemas"
    schema_dir.mkdir(parents=True)
    (schema_dir / f"{page_path}.json").parent.mkdir(parents=True, exist_ok=True)
    (schema_dir / f"{page_path}.json").write_text(json.dumps({
        "schemaVersion": "2", "id": page_path, "route": f"/{page_path}",
        "meta": {}, "dataSources": [], "root": {"id": "r", "type": "Stack", "props": {}, "children": []}
    }), encoding="utf-8")


def test_find_candidates_above_threshold(tmp_path):
    output_root = tmp_path / "output"
    output_root.mkdir()
    _make_project(output_root, "proj1", "workday", "hr", "users_list", 8.7)
    _make_project(output_root, "proj2", "workday", "hr", "users_detail", 7.9)  # below
    _make_project(output_root, "proj3", "workday", "hr", "leave_dashboard", 8.6, has_high=True)  # high-sev

    candidates = find_candidates(output_root)
    assert len(candidates) == 1
    assert candidates[0]["project_id"] == "proj1"


def test_promote_candidate_writes_to_bank(tmp_path):
    output_root = tmp_path / "output"
    output_root.mkdir()
    _make_project(output_root, "proj1", "workday", "hr", "users_list", 8.7)
    candidates = find_candidates(output_root)
    assert candidates

    bank_root = tmp_path / "reference_pages"
    promoted = promote_candidate(candidates[0], bank_root)
    assert promoted.exists()
    assert promoted.parent.name == "list"  # inferred page_type
    assert promoted.parent.parent.name == "hr"
    assert promoted.parent.parent.parent.name == "workday"

    meta = json.loads((promoted.parent / promoted.name.replace(".json", ".meta.json")).read_text(encoding="utf-8"))
    assert meta["score"] == 8.7
    assert meta["auto_promoted"] is True
