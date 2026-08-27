"""Append-only log of per-page fidelity scores written to
output/<id>/src/contracts/fidelity-log.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _log_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "src" / "contracts" / "fidelity-log.json"


def read_fidelity_log(output_dir: str | Path) -> dict[str, Any]:
    """Return the parsed log dict, or an empty dict if the file is absent."""
    p = _log_path(output_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def append_fidelity_entry(
    *,
    output_dir: str,
    page_path: str,
    score: float,
    issues: list[dict[str, Any]],
    iteration: int,
    passed: bool,
    patches: list[dict[str, Any]] | None = None,
    patch_summary: list[str] | None = None,
    validation_errors: list[str] | None = None,
    exit_status: str | None = None,
    failed_fidelity: bool | None = None,
    wall_clock_ms: int | None = None,
    cost_usd: float | None = None,
    flags: dict[str, Any] | None = None,
    manual_run: bool = False,
) -> None:
    """Append an iteration entry for `page_path`. Creates the file/dir if
    absent. Updates `final_score` and `final_iteration` on every call.

    New optional keyword-only params are backward compatible — all default to
    None / False so existing callers need no changes.
    """
    p = _log_path(output_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    log = read_fidelity_log(output_dir)
    page_entry = log.setdefault(page_path, {"iterations": []})
    iter_entry: dict[str, Any] = {
        "iteration": iteration,
        "score": score,
        "issues": issues,
        "patches": patches or [],
        "pass": passed,
    }
    if patch_summary is not None:
        iter_entry["patch_summary"] = patch_summary
    if validation_errors is not None:
        iter_entry["validation_errors"] = validation_errors
    if manual_run:
        iter_entry["manual_run"] = True
    page_entry["iterations"].append(iter_entry)
    page_entry["final_score"] = score
    page_entry["final_iteration"] = iteration
    if exit_status is not None:
        page_entry["exit_status"] = exit_status
    if failed_fidelity is not None:
        page_entry["failed_fidelity"] = failed_fidelity
    if wall_clock_ms is not None:
        page_entry["wall_clock_ms"] = wall_clock_ms
    if cost_usd is not None:
        page_entry["cost_usd"] = cost_usd
    if flags is not None:
        page_entry["flags"] = flags
    p.write_text(json.dumps(log, indent=2))
