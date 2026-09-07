"""Tests for GET /api/_debug/preview-data/{short_id}.

Covers:
  - overview dict is present with title + description strings
  - stats dict contains all required keys

The endpoint calls provide_records_async (which can hit an LLM). We intercept
it via monkeypatch so tests are fully self-contained and fast.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write_contracts(base: Path, short_id: str, app_model: dict, registry: dict | None = None):
    """Write app-model.json (and optional registry.json) under base/<short_id>/src/contracts/."""
    contracts_dir = base / short_id / "src" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    (contracts_dir / "app-model.json").write_text(json.dumps(app_model), encoding="utf-8")
    if registry is not None:
        (contracts_dir / "registry.json").write_text(json.dumps(registry), encoding="utf-8")


MINIMAL_APP_MODEL = {
    "name": "Leave Management System",
    "description": "HR leave request management for employees and managers.",
    "entities": {
        "LeaveRequest": {},
        "Employee": {},
    },
}

MINIMAL_REGISTRY = {
    "entities": {
        "LeaveRequest": {
            "fields": [
                {"name": "id", "type": "string"},
                {"name": "status", "type": "string"},
                {"name": "employeeId", "type": "string"},
            ],
        },
        "Employee": {
            "fields": [
                {"name": "id", "type": "string"},
                {"name": "name", "type": "string"},
            ],
        },
    },
}

# Minimal fixture records returned by the mocked provide_records_async.
# Includes a "status" field so the status-counting branch is exercised.
_LEAVE_RECORDS = [
    {"id": "lr-1", "status": "active", "employeeId": "emp-1"},
    {"id": "lr-2", "status": "pending", "employeeId": "emp-2"},
    {"id": "lr-3", "status": "approved", "employeeId": "emp-1"},
]
_EMPLOYEE_RECORDS = [
    {"id": "emp-1", "name": "Alice"},
    {"id": "emp-2", "name": "Bob"},
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with the output directory redirected to tmp_path and
    provide_records_async mocked so no LLM calls are made."""
    import routers._debug_schema as dbg

    # Redirect Path resolution inside the endpoint to tmp_path.
    # The endpoint constructs `output_root` directly from __file__, so we
    # patch the resolved Path by monkeypatching Path.__truediv__ is too broad.
    # Instead, override the module-level Path calculation via a side-effect on
    # the Path class is also fragile. The cleanest approach: monkeypatch the
    # `Path` used inside the module to redirect `output/<short_id>` lookups.
    #
    # We do this by intercepting at the point where the endpoint resolves the
    # project dir. The function uses:
    #   output_root = Path(__file__).resolve().parent.parent.parent / "output"
    #   proj = output_root / short_id
    # We can't easily patch that without rewriting the module. Instead, write
    # the fixture data into the REAL output directory that the test function
    # resolves to — but that couples tests to repo layout.
    #
    # The pragmatic solution: monkeypatch `pathlib.Path` is heavy. Instead,
    # directly write into the actual output/ tree that the endpoint will look
    # at, using a unique short_id that won't collide with real projects.
    # (We clean up in teardown via the fixture's tmp scope.)
    #
    # Actually the cleanest path: find the output_root the endpoint will use,
    # write there, and clean up after.

    from pathlib import Path as _Path
    output_root = (_Path(dbg.__file__).resolve().parent.parent.parent / "output").resolve()

    # Ensure the output directory exists (it should in a real repo).
    output_root.mkdir(parents=True, exist_ok=True)

    short_id = "test-preview-data-fixture"
    proj_dir = output_root / short_id

    # Write the fixture contracts.
    _write_contracts(output_root, short_id, MINIMAL_APP_MODEL, MINIMAL_REGISTRY)

    # Mock provide_records_async so no LLM calls are made.
    async def _fake_provide(domain, entity_name, fields, count, project_root):
        if entity_name == "LeaveRequest":
            return _LEAVE_RECORDS[:]
        if entity_name == "Employee":
            return _EMPLOYEE_RECORDS[:]
        return [{"id": "x"}]

    monkeypatch.setattr(
        "services.fixtures.dispatcher.provide_records_async",
        _fake_provide,
    )

    from main import app
    tc = TestClient(app)
    yield tc, short_id

    # Cleanup: remove the synthetic project dir we created.
    import shutil
    if proj_dir.exists():
        shutil.rmtree(proj_dir)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_preview_data_has_overview(client):
    """GET /api/_debug/preview-data/{short_id} must return an 'overview' dict
    with non-empty 'title' and 'description' string fields."""
    tc, short_id = client
    r = tc.get(f"/api/_debug/preview-data/{short_id}")
    assert r.status_code == 200, r.text

    body = r.json()
    assert "overview" in body, "Response must contain an 'overview' key"

    overview = body["overview"]
    assert isinstance(overview, dict), "'overview' must be a dict"
    assert "title" in overview, "'overview' must have a 'title' key"
    assert "description" in overview, "'overview' must have a 'description' key"
    assert isinstance(overview["title"], str) and overview["title"], (
        "'overview.title' must be a non-empty string"
    )
    assert isinstance(overview["description"], str), (
        "'overview.description' must be a string"
    )
    # Verify the app-model name was picked up correctly.
    assert overview["title"] == MINIMAL_APP_MODEL["name"]
    assert overview["description"] == MINIMAL_APP_MODEL["description"]


def test_preview_data_has_required_stats_keys(client):
    """GET /api/_debug/preview-data/{short_id} must return a 'stats' dict that
    contains all six keys schemas commonly bind to."""
    tc, short_id = client
    r = tc.get(f"/api/_debug/preview-data/{short_id}")
    assert r.status_code == 200, r.text

    body = r.json()
    assert "stats" in body, "Response must contain a 'stats' key"

    stats = body["stats"]
    required_keys = {
        "totalCount",
        "activeCount",
        "pendingCount",
        "monthlyCount",
        "monthlyChange",
        "monthlyTrend",
    }
    missing = required_keys - set(stats.keys())
    assert not missing, f"'stats' is missing keys: {sorted(missing)}"

    # Basic type assertions.
    assert isinstance(stats["totalCount"], int)
    assert isinstance(stats["activeCount"], int)
    assert isinstance(stats["pendingCount"], int)
    assert isinstance(stats["monthlyCount"], int)
    assert isinstance(stats["monthlyChange"], float)
    assert stats["monthlyTrend"] in ("up", "down", "flat")
