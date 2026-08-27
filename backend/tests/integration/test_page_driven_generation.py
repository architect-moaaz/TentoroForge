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

    # Exactly 2 schema files emitted, no list/detail/form trio
    found = sorted([
        str(p.relative_to(tmp_path / "src" / "schemas"))
        for p in (tmp_path / "src" / "schemas").rglob("*.json")
    ])
    assert found == ["notes.json", "notes/new.json"], f"unexpected files: {found}"

    # registry.ts is keyed by route
    registry = (tmp_path / "src" / "schemas" / "registry.ts").read_text()
    assert '"/notes": () => import("./notes.json")' in registry
    assert '"/notes/new": () => import("./notes/new.json")' in registry
