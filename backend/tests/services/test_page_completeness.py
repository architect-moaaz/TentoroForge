import json
from pathlib import Path

import pytest

from services.page_completeness import fill_missing_pages
from services.route_slug import slugify_route


@pytest.mark.asyncio
async def test_continuation_generates_then_floors_the_rest(tmp_path, monkeypatch):
    plan = {"pages": [
        {"route": "/a", "type": "list", "entity": "A"},
        {"route": "/b", "type": "form", "entity": "B"},
    ]}
    (tmp_path / "src" / "schemas").mkdir(parents=True)

    async def fake_agent(output_dir, plan, page, domain_context=None):
        if page["route"] == "/a":  # LLM "succeeds" for /a
            slug = slugify_route("/a")
            (Path(output_dir) / "src" / "schemas" / f"{slug}.json").write_text(
                '{"id":"a","root":{"type":"Stack"}}')
            return
        raise RuntimeError("wedged")  # LLM "fails" for /b

    monkeypatch.setattr("agents.page_schema_agent.run_page_schema_agent", fake_agent)

    res = await fill_missing_pages(str(tmp_path), plan)

    assert "/a" in res["llm"]       # produced by per-page continuation
    assert "/b" in res["minimal"]   # floored deterministically
    assert (tmp_path / "src" / "schemas" / "a.json").exists()
    floored = tmp_path / "src" / "schemas" / "b.json"
    assert floored.exists()
    assert json.loads(floored.read_text()).get("id") == "b"


@pytest.mark.asyncio
async def test_noop_when_all_pages_present(tmp_path, monkeypatch):
    plan = {"pages": [{"route": "/a", "type": "list"}]}
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "a.json").write_text('{"id":"a"}')

    called = {"n": 0}

    async def fake_agent(*a, **k):
        called["n"] += 1

    monkeypatch.setattr("agents.page_schema_agent.run_page_schema_agent", fake_agent)
    res = await fill_missing_pages(str(tmp_path), plan)
    assert res == {"llm": [], "minimal": [], "failed": []}
    assert called["n"] == 0
