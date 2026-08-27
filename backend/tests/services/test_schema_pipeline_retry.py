"""Regression tests for the two-pass retry + per-page error capture added to
_emit_per_page in schema_pipeline.py.

Scenarios covered:
  1. Transient failures on pass 1 → recovered on pass 2 → all pages present on disk.
  2. Permanent failures (fail on every call) → only those pages end up as stubs;
     summary event correctly reports succeeded/total counts.
  3. Malformed (non-dict) page entries are skipped without crashing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helper — collect all SSE events from the pipeline into a flat list.
# ---------------------------------------------------------------------------

async def _collect(gen) -> list[dict]:
    return [e async for e in gen]


def _log_texts(events: list[dict]) -> list[str]:
    """Extract the 'text' field from all log SSE events."""
    out = []
    for e in events:
        data = e.get("data") or ""
        if e.get("event") == "log" and isinstance(data, str) and "[Schema]" in data:
            out.append(data)
    return out


# ---------------------------------------------------------------------------
# Test 1: transient failures recover on retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_pass_retry_recovers_transient_failures(tmp_path):
    """Pages that fail on pass 1 but succeed on retry end up on disk; summary
    reports all 3/3 succeeded."""
    from services.schema_pipeline import run_schema_frontend_pipeline

    call_log: list[str] = []
    fail_first_time = {"/audit-logs", "/users"}

    async def fake_agent(output_dir, plan, page, domain_context=None):
        route = page.get("route", "")
        call_log.append(route)
        # Fail only on the first call for these routes; succeed on subsequent calls.
        if route in fail_first_time and call_log.count(route) == 1:
            raise RuntimeError(f"transient error for {route}")
        # Write a minimal schema so the file exists.
        slug = route.strip("/") or "home"
        f = Path(output_dir) / "src" / "schemas" / f"{slug}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"id": slug}))

    plan = {
        "pages": [
            {"route": "/audit-logs", "id": "audit-logs"},
            {"route": "/users",      "id": "users"},
            {"route": "/tasks",      "id": "tasks"},
        ]
    }

    with patch("agents.page_schema_agent.run_page_schema_agent", side_effect=fake_agent):
        events = await _collect(
            run_schema_frontend_pipeline(str(tmp_path), plan, "test")
        )

    # All 3 schema files must exist on disk (no stubs needed).
    for slug in ["audit-logs", "users", "tasks"]:
        assert (tmp_path / "src" / "schemas" / f"{slug}.json").exists(), \
            f"Missing schema file: {slug}.json"

    logs = _log_texts(events)
    # Summary event must mention 3/3 succeeded.
    assert any("3/3" in t for t in logs), \
        f"Expected '3/3' in summary. Logs: {logs}"
    # Retry log must mention the 2 failed pages.
    assert any("Retrying 2 failed" in t for t in logs), \
        f"Expected retry announcement. Logs: {logs}"
    # Pass-2 success markers present.
    assert any("(retry)" in t and "/audit-logs" in t for t in logs)
    assert any("(retry)" in t and "/users" in t for t in logs)

    # /audit-logs and /users each called twice; /tasks called once.
    assert call_log.count("/audit-logs") == 2
    assert call_log.count("/users") == 2
    assert call_log.count("/tasks") == 1


# ---------------------------------------------------------------------------
# Test 2: permanent failures produce stubs + correct summary counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_permanent_failures_become_stubs_with_correct_summary(tmp_path):
    """Pages that fail on both passes end up as stubs (via _fill_missing_with_stubs).
    The summary event reports the right succeeded/total numbers."""
    from services.schema_pipeline import run_schema_frontend_pipeline

    always_fail = {"/login", "/signup"}

    async def fake_agent(output_dir, plan, page, domain_context=None):
        route = page.get("route", "")
        if route in always_fail:
            raise ValueError(f"permanent error for {route}")
        slug = route.strip("/") or "home"
        f = Path(output_dir) / "src" / "schemas" / f"{slug}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"id": slug}))

    plan = {
        "pages": [
            {"route": "/dashboard", "id": "dashboard"},
            {"route": "/login",     "id": "login",  "type": "auth"},
            {"route": "/signup",    "id": "signup", "type": "auth"},
        ]
    }

    with patch("agents.page_schema_agent.run_page_schema_agent", side_effect=fake_agent):
        events = await _collect(
            run_schema_frontend_pipeline(str(tmp_path), plan, "test")
        )

    logs = _log_texts(events)

    # Summary event should report 1/3 succeeded.
    assert any("1/3" in t for t in logs), \
        f"Expected '1/3' in summary. Logs: {logs}"

    # Stubs must have been written for the two failed pages.
    stub_log = [t for t in logs if "stub" in t.lower()]
    assert stub_log, "Expected stub-written log message"

    # Error-type grouping line for ValueError should appear.
    assert any("ValueError" in t for t in logs), \
        f"Expected error-type grouping. Logs: {logs}"

    # Stub files exist for failed pages.
    for slug in ["login", "signup"]:
        stub_path = tmp_path / "src" / "schemas" / f"{slug}.json"
        assert stub_path.exists(), f"Expected stub file for {slug}"
        stub_data = json.loads(stub_path.read_text())
        assert stub_data.get("schemaVersion") == "2", \
            "Stub should have schemaVersion=2"


# ---------------------------------------------------------------------------
# Test 3: malformed page entries skipped gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_page_entries_skipped_without_crash(tmp_path):
    """Non-dict entries in plan.pages do not crash the pipeline; valid pages
    still get processed."""
    from services.schema_pipeline import run_schema_frontend_pipeline

    processed: list[str] = []

    async def fake_agent(output_dir, plan, page, domain_context=None):
        route = page.get("route", "")
        processed.append(route)
        slug = route.strip("/") or "home"
        f = Path(output_dir) / "src" / "schemas" / f"{slug}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"id": slug}))

    plan = {
        "pages": [
            "not-a-dict",          # malformed
            None,                  # malformed
            {"route": "/tasks"},   # valid
        ]
    }

    with patch("agents.page_schema_agent.run_page_schema_agent", side_effect=fake_agent):
        events = await _collect(
            run_schema_frontend_pipeline(str(tmp_path), plan, "test")
        )

    # Only /tasks should have been processed.
    assert processed == ["/tasks"]

    # Pipeline should not have raised.
    assert any(
        "tasks" in (e.get("data") or "") for e in events
    ), "Expected /tasks to be mentioned in events"
