import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from agents.page_schema_agent import run_page_schema_agent


@pytest.mark.asyncio
async def test_emits_one_file_at_route_path(tmp_path):
    plan = {
        "entities": {"Note": {"fields": [{"name": "title", "type": "string"}]}},
    }
    page = {"route": "/notes", "entity": "Note", "type": "list", "name": "NoteList"}

    fake_schema = {
        "schemaVersion": "2", "id": "ignored",
        "route": "/notes", "layout": "main",
        "root": {"type": "Stack", "id": "r", "children": []},
    }
    with patch(
        "agents.page_schema_agent._generate_schema_for_page",
        new=AsyncMock(return_value=fake_schema),
    ):
        await run_page_schema_agent(str(tmp_path), plan, page)

    written = tmp_path / "src" / "schemas" / "notes.json"
    assert written.exists()
    on_disk = json.loads(written.read_text(encoding="utf-8"))
    # id is overwritten to the slug so the file is self-describing
    assert on_disk["id"] == "notes"
    assert on_disk["route"] == "/notes"


@pytest.mark.asyncio
async def test_nested_route_creates_subdirectories(tmp_path):
    plan = {"entities": {"Note": {"fields": []}}}
    page = {"route": "/notes/new", "entity": "Note", "type": "form", "name": "NewNote"}
    fake_schema = {"schemaVersion": "2", "id": "x", "route": "/notes/new", "layout": "main",
                   "root": {"type": "Stack", "id": "r", "children": []}}
    with patch(
        "agents.page_schema_agent._generate_schema_for_page",
        new=AsyncMock(return_value=fake_schema),
    ):
        await run_page_schema_agent(str(tmp_path), plan, page)
    assert (tmp_path / "src" / "schemas" / "notes" / "new.json").exists()


@pytest.mark.asyncio
async def test_home_route_writes_home_json(tmp_path):
    plan = {"entities": {}}
    page = {"route": "/", "entity": None, "type": "dashboard", "name": "Home"}
    fake_schema = {"schemaVersion": "2", "id": "x", "route": "/", "layout": "main",
                   "root": {"type": "Stack", "id": "r", "children": []}}
    with patch(
        "agents.page_schema_agent._generate_schema_for_page",
        new=AsyncMock(return_value=fake_schema),
    ):
        await run_page_schema_agent(str(tmp_path), plan, page)
    assert (tmp_path / "src" / "schemas" / "home.json").exists()
