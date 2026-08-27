import json
from pathlib import Path

from services.fidelity_log import append_fidelity_entry, read_fidelity_log


def test_append_creates_file_when_absent(tmp_path: Path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    append_fidelity_entry(
        output_dir=str(output_dir),
        page_path="users/list",
        score=7.4,
        issues=[{"severity": "medium", "issue": "sparse"}],
        iteration=0,
        passed=False,
    )
    log = read_fidelity_log(str(output_dir))
    assert "users/list" in log
    assert log["users/list"]["iterations"][0]["score"] == 7.4


def test_append_extends_existing_page_iterations(tmp_path: Path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    append_fidelity_entry(output_dir=str(output_dir), page_path="users/list", score=6.0,
                          issues=[], iteration=0, passed=False)
    append_fidelity_entry(output_dir=str(output_dir), page_path="users/list", score=8.1,
                          issues=[], iteration=1, passed=True)
    log = read_fidelity_log(str(output_dir))
    assert len(log["users/list"]["iterations"]) == 2
    assert log["users/list"]["final_score"] == 8.1
    assert log["users/list"]["final_iteration"] == 1


def test_separate_pages_kept_separate(tmp_path: Path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    append_fidelity_entry(output_dir=str(output_dir), page_path="a", score=5, issues=[], iteration=0, passed=False)
    append_fidelity_entry(output_dir=str(output_dir), page_path="b", score=8, issues=[], iteration=0, passed=True)
    log = read_fidelity_log(str(output_dir))
    assert set(log) == {"a", "b"}


def test_append_with_extended_fields(tmp_path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    from services.fidelity_log import append_fidelity_entry, read_fidelity_log
    append_fidelity_entry(
        output_dir=str(output_dir), page_path="users/list",
        score=8.4, issues=[], iteration=2, passed=True,
        patches=[{"op": "replace", "path": "/x", "value": "y"}],
        patch_summary=["replaced /x"],
        validation_errors=[],
        exit_status="pass",
        wall_clock_ms=18000, cost_usd=0.18,
        flags={"fidelity_loop": True, "reference_grounding": True, "loop_version": "v1"},
    )
    log = read_fidelity_log(str(output_dir))
    entry = log["users/list"]
    assert entry["final_score"] == 8.4
    assert entry["exit_status"] == "pass"
    assert entry["flags"]["loop_version"] == "v1"
    assert entry["wall_clock_ms"] == 18000
    assert entry["cost_usd"] == 0.18


def test_append_with_failed_fidelity_marks_warning(tmp_path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    from services.fidelity_log import append_fidelity_entry, read_fidelity_log
    append_fidelity_entry(
        output_dir=str(output_dir), page_path="users/detail",
        score=7.6, issues=[{"severity": "high"}], iteration=3, passed=False,
        exit_status="failed", failed_fidelity=True,
        wall_clock_ms=88000, cost_usd=0.42,
    )
    log = read_fidelity_log(str(output_dir))
    assert log["users/detail"]["failed_fidelity"] is True
    assert log["users/detail"]["exit_status"] == "failed"


def test_manual_run_flag_persists(tmp_path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    from services.fidelity_log import append_fidelity_entry, read_fidelity_log
    append_fidelity_entry(output_dir=str(output_dir), page_path="users/list",
                          score=8.0, issues=[], iteration=0, passed=True)
    append_fidelity_entry(output_dir=str(output_dir), page_path="users/list",
                          score=8.5, issues=[], iteration=1, passed=True,
                          manual_run=True)
    log = read_fidelity_log(str(output_dir))
    iters = log["users/list"]["iterations"]
    assert iters[1]["manual_run"] is True
    assert iters[0].get("manual_run") in (None, False)
