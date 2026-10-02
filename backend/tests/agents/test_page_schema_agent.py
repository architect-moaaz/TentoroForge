"""Where a page schema lands on disk, and under what name.

THE PAGE TYPE HAD TO CHANGE HERE TOO. These asked for a `list`, a `form` and
a `dashboard`; the Collection, Record and Dashboard Authority phases made all
three the deterministic composers' to write, so `run_page_schema_agent`
returns before authoring one and nothing reached disk. `settings` is a kind no
composer claims, so the slug-to-path contract these exist for still runs.

The home-route case could not be rescued that way: dashboard authority
backstops on the ROUTE, so `/` belongs to the composer whatever its type says.
It asserts the naming rule at `slugify_route`, which is the part of it that
survived.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from agents.page_schema_agent import run_page_schema_agent, slugify_route


@pytest.mark.asyncio
async def test_emits_one_file_at_route_path(tmp_path):
    plan = {
        "entities": {"Note": {"fields": [{"name": "title", "type": "string"}]}},
    }
    page = {"route": "/notes", "entity": "Note", "type": "settings", "name": "NoteList"}

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
    on_disk = json.loads(written.read_text())
    # id is overwritten to the slug so the file is self-describing
    assert on_disk["id"] == "notes"
    assert on_disk["route"] == "/notes"


@pytest.mark.asyncio
async def test_nested_route_creates_subdirectories(tmp_path):
    plan = {"entities": {"Note": {"fields": []}}}
    page = {"route": "/notes/new", "entity": "Note", "type": "settings", "name": "NewNote"}
    fake_schema = {"schemaVersion": "2", "id": "x", "route": "/notes/new", "layout": "main",
                   "root": {"type": "Stack", "id": "r", "children": []}}
    with patch(
        "agents.page_schema_agent._generate_schema_for_page",
        new=AsyncMock(return_value=fake_schema),
    ):
        await run_page_schema_agent(str(tmp_path), plan, page)
    assert (tmp_path / "src" / "schemas" / "notes" / "new.json").exists()


def test_home_route_is_named_home():
    """`/` is filed as `home`, so the registry key and the file agree.

    Asserted at `slugify_route` rather than through the agent: dashboard
    authority backstops on the ROUTE, so `/` is the composer's to write
    whatever the page type says, and no call through the agent can put a file
    there any more. The naming rule is the part of this that survived.
    """
    assert slugify_route("/") == "home"
