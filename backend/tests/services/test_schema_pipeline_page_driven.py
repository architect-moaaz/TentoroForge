import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from services.schema_pipeline import run_schema_frontend_pipeline


@pytest.mark.asyncio
async def test_emits_one_file_per_plan_page(tmp_path):
    plan = {
        "entities": {"Note": {"fields": []}},
        "pages": [
            {"route": "/notes",     "entity": "Note", "type": "list", "name": "List"},
            {"route": "/notes/new", "entity": "Note", "type": "form", "name": "New"},
        ],
    }
    captured = []
    async def fake_agent(output_dir, plan_in, page, domain_context=None):
        captured.append(page["route"])
        # Simulate the agent writing a file (so the pipeline can finalize registry.ts)
        from services.route_slug import slugify_route
        slug = slugify_route(page["route"])
        out_path = Path(output_dir) / "src" / "schemas" / f"{slug}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("{}")

    with patch("agents.page_schema_agent.run_page_schema_agent", new=fake_agent):
        events = []
        async for evt in run_schema_frontend_pipeline(
            output_dir=str(tmp_path), plan=plan, description="test",
        ):
            events.append(evt)

    assert captured == ["/notes", "/notes/new"]
    assert (tmp_path / "src" / "schemas" / "notes.json").exists()
    assert (tmp_path / "src" / "schemas" / "notes" / "new.json").exists()
    # Registry generated
    registry = (tmp_path / "src" / "schemas" / "registry.ts").read_text()
    assert '"/notes": () => import("./notes.json")' in registry
    assert '"/notes/new": () => import("./notes/new.json")' in registry


@pytest.mark.asyncio
async def test_no_plan_pages_falls_back_to_entity_trio(tmp_path):
    """When plan.pages is empty, fall back to the legacy entity-driven path
    so existing plans keep working."""
    plan = {"entities": {"Note": {"fields": []}}, "pages": []}
    legacy_calls = []
    async def fake_legacy(output_dir, plan_in, domain_context=None):
        legacy_calls.append(plan_in.get("entity", {}).get("name"))

    with patch("agents.feature_slice_schema_agent.run_feature_slice_schema_agent", new=fake_legacy):
        async for _ in run_schema_frontend_pipeline(
            output_dir=str(tmp_path), plan=plan, description="test",
        ):
            pass

    assert legacy_calls == ["Note"]
