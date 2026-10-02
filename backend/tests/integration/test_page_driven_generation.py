import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services.schema_pipeline import run_schema_frontend_pipeline


@pytest.mark.asyncio
async def test_two_page_plan_emits_exactly_two_files(tmp_path):
    plan = {
        "name": "Notes",
        "entities": {"Note": {"fields": [{"name": "title", "type": "string"}]}},
        "pages": [
            {"route": "/notes",     "entity": "Note", "type": "list", "name": "List"},
            {"route": "/notes/new", "entity": "Note", "type": "form", "name": "New"},
        ],
        "design_spec": {"register": "default"},
    }

    def make_fake_schema(slug: str) -> dict:
        return {
            "schemaVersion": "2", "id": slug,
            "route": "/" + slug if slug != "home" else "/",
            "layout": "main",
            "root": {"type": "Stack", "id": "r", "children": []},
        }

    async def fake_generate(plan_in, page, slug, domain_context):
        return make_fake_schema(slug)

    with patch(
        "agents.page_schema_agent._generate_schema_for_page",
        new=AsyncMock(side_effect=fake_generate),
    ):
        async for _ in run_schema_frontend_pipeline(
            output_dir=str(tmp_path), plan=plan, description="x",
        ):
            pass

    # THE PLAN'S PAGES, PLUS THE EDIT FORM THE PIPELINE GUARANTEES — and no
    # invented detail page.
    #
    # This asserted exactly two files. `ensure_edit_routes` materialises the
    # missing `/x/[id]/edit` form at generation time, because an Edit button
    # pointing at a route nobody planned is a 404 the user finds, so a two-page
    # plan legitimately emits three. What this test is really for is that the
    # pipeline does NOT fabricate a whole list/detail/form trio per entity, and
    # it still does not: there is no `/notes/[id]` detail page below.
    found = sorted([
        str(p.relative_to(tmp_path / "src" / "schemas"))
        for p in (tmp_path / "src" / "schemas").rglob("*.json")
    ])
    assert found == ["notes.json", "notes/[id]/edit.json", "notes/new.json"], (
        f"unexpected files: {found}")
    assert "notes/[id].json" not in found, "a detail page nobody planned"

    # registry.ts is keyed by route
    registry = (tmp_path / "src" / "schemas" / "registry.ts").read_text()
    assert '"/notes": () => import("./notes.json")' in registry
    assert '"/notes/new": () => import("./notes/new.json")' in registry
