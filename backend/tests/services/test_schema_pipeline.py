"""Tests for run_schema_frontend_pipeline behaviour, focused on the
skip_routes flag added in P3.T1."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_skip_routes_filters_pages(tmp_path):
    """Routes in skip_routes do not get LLM-emitted."""
    from services.schema_pipeline import run_schema_frontend_pipeline
    plan = {"pages": [
        {"route": "/login",     "file": "src/schemas/login.json"},
        {"route": "/dashboard", "file": "src/schemas/dashboard.json"},
        {"route": "/settings",  "file": "src/schemas/settings.json"},
    ]}
    # Mock the agent so no actual LLM call happens — we just want to verify
    # which pages get iterated.
    emitted_routes = []
    async def fake_run(output_dir, plan, page, **kw):
        emitted_routes.append(page["route"])
    with patch("agents.page_schema_agent.run_page_schema_agent", side_effect=fake_run):
        events = []
        async for evt in run_schema_frontend_pipeline(
            str(tmp_path), plan, "test",
            skip_routes={"/login", "/settings"},
        ):
            events.append(evt)
    # Only /dashboard should have been emitted
    assert emitted_routes == ["/dashboard"]
    # Skip log emitted
    skip_logs = [e for e in events if e.get("event") == "log"
                                       and "Skipping 2 page" in (e.get("data") or "")]
    assert len(skip_logs) >= 1


@pytest.mark.asyncio
async def test_skip_routes_none_means_no_filtering(tmp_path):
    """When skip_routes is None (default), all pages are emitted."""
    from services.schema_pipeline import run_schema_frontend_pipeline
    plan = {"pages": [
        {"route": "/x", "file": "src/schemas/x.json"},
        {"route": "/y", "file": "src/schemas/y.json"},
    ]}
    emitted = []
    async def fake_run(output_dir, plan, page, **kw):
        emitted.append(page["route"])
    with patch("agents.page_schema_agent.run_page_schema_agent", side_effect=fake_run):
        async for _ in run_schema_frontend_pipeline(str(tmp_path), plan, "test"):
            pass
    assert sorted(emitted) == ["/x", "/y"]


@pytest.mark.asyncio
async def test_skip_routes_all_skipped_uses_no_legacy_path(tmp_path):
    """When EVERY page is skipped, pipeline should NOT fall through to the
    legacy entity-trio path — that would re-emit junk. With pages=[] after
    filtering, the legacy path shouldn't fire."""
    from services.schema_pipeline import run_schema_frontend_pipeline
    plan = {"pages": [{"route": "/x", "file": "src/schemas/x.json"}]}
    with patch("agents.page_schema_agent.run_page_schema_agent",
               AsyncMock(side_effect=AssertionError("should not run"))):
        # Also block the legacy path
        with patch("agents.feature_slice_schema_agent.run_feature_slice_schema_agent",
                   AsyncMock(side_effect=AssertionError("legacy should not run"))):
            events = []
            async for evt in run_schema_frontend_pipeline(
                str(tmp_path), plan, "test",
                skip_routes={"/x"},
            ):
                events.append(evt)
    # No assertion errors raised — neither path ran.
