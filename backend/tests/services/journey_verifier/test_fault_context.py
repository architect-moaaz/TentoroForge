"""Unit tests for the V&F 2.0 fault context builder (M2).

Pure builder — reads files from a tmp_path fixture, no LLM. We verify:

  * SmithContext dataclass shape
  * page_schema / page_code lookup finds the file
  * page_schema / page_code returns None when the file is missing
  * console filter drops non-err levels
  * network filter drops <400
  * infer_entities_from_route parses slugs correctly
  * git_log_since_last_verify returns [] when output_dir is not a repo
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from services.journey_verifier.fault_classifier import ClassifiedFault
from services.journey_verifier.fault_context import (
    SmithContext,
    build_fault_context,
    git_log_since_last_verify,
    infer_entities_from_route,
    _filter_console_errors,
    _filter_network_failures,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


def _cf(
    *,
    route: str = "/applicants",
    class_name: str = "render-error",
    seam: str = "smith:render",
    evidence: dict | None = None,
) -> ClassifiedFault:
    raw = {
        "interaction": {"id": f"route:{route}", "route": route, "kind": "route"},
        "evidence": evidence or {},
    }
    return ClassifiedFault(
        interaction_id=f"route:{route}",
        route=route,
        class_name=class_name,
        seam=seam,
        evidence_slice="test",
        needed_context=[],
        raw=raw,
    )


# ── Dataclass shape ─────────────────────────────────────────────────────────


def test_smith_context_dataclass_shape(tmp_path: Path):
    ctx = build_fault_context(_cf(route="/x"), tmp_path)
    assert isinstance(ctx, SmithContext)
    # Every declared field exists
    for field_name in (
        "symptom", "route", "page_schema", "page_code",
        "console_errors", "network_failures", "related_entities",
        "recent_edits", "available_tools",
    ):
        assert hasattr(ctx, field_name)
    # Types
    assert isinstance(ctx.symptom, str)
    assert isinstance(ctx.console_errors, list)
    assert isinstance(ctx.network_failures, list)
    assert isinstance(ctx.related_entities, list)
    assert isinstance(ctx.recent_edits, list)
    assert isinstance(ctx.available_tools, list)


# ── page_schema lookup ──────────────────────────────────────────────────────


def test_page_schema_found_via_naive_path(tmp_path: Path):
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "applicants.json").write_text(
        json.dumps({"route": "/applicants", "kind": "list"}),
        encoding="utf-8",
    )
    ctx = build_fault_context(_cf(route="/applicants"), tmp_path)
    assert ctx.page_schema is not None
    assert "/applicants" in ctx.page_schema


def test_page_schema_returns_none_when_missing(tmp_path: Path):
    ctx = build_fault_context(_cf(route="/nowhere"), tmp_path)
    assert ctx.page_schema is None


def test_page_schema_scan_fallback(tmp_path: Path):
    """Schema on disk with a different filename but matching top-level route."""
    schemas = tmp_path / "src" / "schemas" / "nested"
    schemas.mkdir(parents=True)
    (schemas / "weird-name.json").write_text(
        json.dumps({"route": "/applicants", "kind": "list"}),
        encoding="utf-8",
    )
    ctx = build_fault_context(_cf(route="/applicants"), tmp_path)
    assert ctx.page_schema is not None
    assert '"route": "/applicants"' in ctx.page_schema


# ── page_code lookup ────────────────────────────────────────────────────────


def test_page_code_found_at_literal_path(tmp_path: Path):
    p = tmp_path / "src" / "app" / "tasks" / "page.tsx"
    p.parent.mkdir(parents=True)
    p.write_text("export default function TasksPage() { return null; }", encoding="utf-8")
    ctx = build_fault_context(_cf(route="/tasks"), tmp_path)
    assert ctx.page_code is not None
    assert "TasksPage" in ctx.page_code


def test_page_code_found_under_dashboard_group(tmp_path: Path):
    p = tmp_path / "src" / "app" / "(dashboard)" / "reports" / "page.tsx"
    p.parent.mkdir(parents=True)
    p.write_text("// ReportsPage source", encoding="utf-8")
    ctx = build_fault_context(_cf(route="/reports"), tmp_path)
    assert ctx.page_code is not None
    assert "ReportsPage" in ctx.page_code


def test_page_code_returns_none_when_missing(tmp_path: Path):
    ctx = build_fault_context(_cf(route="/does-not-exist"), tmp_path)
    assert ctx.page_code is None


# ── console filter ──────────────────────────────────────────────────────────


def test_console_filter_drops_non_err_levels():
    entries = [
        {"level": "err", "text": "kept 1"},
        {"level": "log", "text": "dropped"},
        {"level": "warn", "text": "dropped"},
        {"level": "error", "text": "kept 2"},   # alias
        {"level": "ERROR", "text": "kept 3"},   # case-insensitive
        {"level": "info", "text": "dropped"},
    ]
    out = _filter_console_errors(entries)
    kept = [e["text"] for e in out]
    assert kept == ["kept 1", "kept 2", "kept 3"]


def test_console_filter_capped_at_10():
    entries = [{"level": "err", "text": f"e{i}"} for i in range(15)]
    out = _filter_console_errors(entries)
    assert len(out) == 10


# ── network filter ──────────────────────────────────────────────────────────


def test_network_filter_drops_below_400():
    entries = [
        {"url": "/a", "status": 200},
        {"url": "/b", "status": 301},
        {"url": "/c", "status": 400},   # kept
        {"url": "/d", "status": 404},   # kept
        {"url": "/e", "status": 500},   # kept
        {"url": "/f"},                   # no status → dropped
        {"url": "/g", "status": "oops"}, # bad type → dropped
    ]
    out = _filter_network_failures(entries)
    urls = [e["url"] for e in out]
    assert urls == ["/c", "/d", "/e"]


def test_network_filter_capped_at_10():
    entries = [{"url": f"/x{i}", "status": 500} for i in range(15)]
    out = _filter_network_failures(entries)
    assert len(out) == 10


# ── infer_entities_from_route ───────────────────────────────────────────────


def test_infer_entities_basic():
    assert infer_entities_from_route("/applicants") == ["applicants"]
    assert infer_entities_from_route("/applicants/new") == ["applicants"]
    assert infer_entities_from_route("/admin/roles/[id]/edit") == ["admin", "roles"]
    assert infer_entities_from_route("/") == []
    assert infer_entities_from_route("") == []


def test_infer_entities_dedupes():
    # No duplicates even if the segment appears twice
    assert infer_entities_from_route("/foo/foo/bar") == ["foo", "bar"]


def test_infer_entities_filters_against_plan(tmp_path: Path):
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "plan.json").write_text(json.dumps({
        "entities": [{"name": "applicants"}, {"name": "roles"}],
    }), encoding="utf-8")
    got = infer_entities_from_route("/admin/roles/[id]", tmp_path)
    # "admin" isn't a plan entity, "roles" is → filter down.
    assert got == ["roles"]


def test_infer_entities_falls_back_when_no_match(tmp_path: Path):
    """If none of the route parts match the plan, still return raw."""
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "plan.json").write_text(json.dumps({
        "entities": [{"name": "orders"}],
    }), encoding="utf-8")
    got = infer_entities_from_route("/reports/summary", tmp_path)
    assert got == ["reports", "summary"]


# ── git_log_since_last_verify ───────────────────────────────────────────────


def test_git_log_returns_empty_when_not_a_repo(tmp_path: Path):
    assert git_log_since_last_verify(tmp_path) == []


def test_git_log_returns_lines_when_repo(tmp_path: Path):
    # Only run if git is actually available on PATH — otherwise skip.
    try:
        subprocess.run(
            ["git", "init", "-q"], cwd=tmp_path, check=True,
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.local"],
            cwd=tmp_path, check=True, capture_output=True, timeout=5,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, check=True, capture_output=True, timeout=5,
        )
        (tmp_path / "README.md").write_text("hi", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md"], cwd=tmp_path, check=True,
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "test commit"],
            cwd=tmp_path, check=True, capture_output=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pytest.skip("git not available")
    lines = git_log_since_last_verify(tmp_path)
    assert len(lines) == 1
    assert "test commit" in lines[0]


# ── Symptom extraction ─────────────────────────────────────────────────────


def test_symptom_trimmed_to_max_length():
    long_stack = "line\n" * 10_000  # way over the cap
    ctx = build_fault_context(
        _cf(route="/x", evidence={"stack_trace": long_stack}),
        Path("/nonexistent-path-should-not-crash"),
    )
    assert 0 < len(ctx.symptom) <= 2000


def test_symptom_falls_through_stack_body_status():
    ctx = build_fault_context(
        _cf(route="/x", evidence={"status": 500}),
        Path("/nonexistent"),
    )
    assert "HTTP 500" in ctx.symptom
    ctx = build_fault_context(
        _cf(route="/x", evidence={"body_excerpt": "boom"}),
        Path("/nonexistent"),
    )
    assert "boom" in ctx.symptom


# ── available_tools wiring ──────────────────────────────────────────────────


def test_available_tools_looked_up_by_seam(tmp_path: Path):
    """The default lookup pulls from smith_autofix.TOOL_SUBSETS."""
    ctx = build_fault_context(_cf(seam="smith:render"), tmp_path)
    assert "edit_page" in ctx.available_tools


def test_available_tools_explicit_override(tmp_path: Path):
    ctx = build_fault_context(
        _cf(seam="smith:render"), tmp_path,
        tool_subset=["only_tool"],
    )
    assert ctx.available_tools == ["only_tool"]
