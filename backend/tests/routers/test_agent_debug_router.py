"""Watching a running app live, through the platform's two endpoints.

Driven the way the other router tests drive endpoints: the function itself, with the project lookup stubbed, a
temp app folder, and the running app faked at the HTTP layer. What is pinned: the platform keeps the secret and
sends it (the browser never sees it), the draft is compiled here and sent as the agent to run, the app's stream
comes back untouched, and a project that was never built says so.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

import models  # noqa: F401  (register every model before test_db.create_all)
from services import agent_debug
from services.agent_debug import ensure_debug_secret

GRAPH = {
    "id": "support",
    "name": "Support Bot",
    "nodes": [
        {"id": "sp", "type": "system_prompt", "position": {"x": 0, "y": 0},
         "data": {"label": "Prompt", "nodeType": "system_prompt", "config": {"prompt": "You help customers."}}},
        {"id": "t1", "type": "tool", "position": {"x": 0, "y": 0},
         "data": {"label": "close_ticket", "nodeType": "tool",
                  "config": {"tool_name": "close_ticket", "tool_type": "data_engine", "entity": "tickets", "operation": "update"}}},
        {"id": "t2", "type": "tool", "position": {"x": 0, "y": 0},
         "data": {"label": "lookup", "nodeType": "tool", "config": {"tool_name": "lookup", "tool_type": "function"}}},
    ],
    "edges": [],
}

REAL_CLIENT = httpx.AsyncClient


class _User:
    id = "u-1"


@pytest.fixture()
def project(tmp_path, monkeypatch):
    proj = SimpleNamespace(id=uuid.uuid4(), output_dir=str(tmp_path))

    async def fake_get(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    return proj


def fake_app(monkeypatch, handler):
    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return REAL_CLIENT(*a, **kw)

    monkeypatch.setattr(agent_debug.httpx, "AsyncClient", factory)


async def drain(response) -> list[dict]:
    raw = b"".join([c async for c in response.body_iterator]).decode()
    return [json.loads(line[6:]) for line in raw.split("\n") if line.startswith("data: ")]


@pytest.mark.asyncio
async def test_status_uses_the_apps_own_key(project, monkeypatch):
    from routers.agent_builder import debug_status

    secret = ensure_debug_secret(__import__("pathlib").Path(project.output_dir))
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.headers.get("x-forge-debug-secret"))
        if req.url.params.get("users"):
            return httpx.Response(200, json={"users": []})
        return httpx.Response(200, json={"agents": [{"id": "support", "name": "Support Bot", "enabled": True}]})

    fake_app(monkeypatch, handler)
    out = await debug_status(project.id, "http://localhost:3000", _User(), None)
    assert out["ok"] is True and out["agents"][0]["id"] == "support" and "users" not in out
    assert set(seen) == {secret}, "the platform sends the key; the browser never holds it"


@pytest.mark.asyncio
async def test_status_for_an_app_with_no_key_says_to_apply(project):
    from routers.agent_builder import debug_status

    out = await debug_status(project.id, "http://localhost:3000", _User(), None)
    assert out["ok"] is False and "Apply the agent once" in out["reason"]


@pytest.mark.asyncio
async def test_status_for_an_address_off_this_computer_is_refused_in_words(project):
    from routers.agent_builder import debug_status

    out = await debug_status(project.id, "http://example.com", _User(), None)
    assert out["ok"] is False and "this computer" in out["reason"]


@pytest.mark.asyncio
async def test_a_project_that_was_never_built_has_no_app_to_run(monkeypatch):
    from routers.agent_builder import debug_status

    proj = SimpleNamespace(id=uuid.uuid4(), output_dir=None)

    async def fake_get(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    with pytest.raises(HTTPException) as e:
        await debug_status(proj.id, "http://localhost:3000", _User(), None)
    assert e.value.status_code == 400 and "not been built" in e.value.detail


@pytest.mark.asyncio
async def test_the_watch_starts_with_the_map_of_the_canvas_then_the_apps_feed(project, monkeypatch):
    from routers.agent_builder import debug_watch
    from schemas.agent_builder import AgentWatch

    ensure_debug_secret(__import__("pathlib").Path(project.output_dir))
    sent = {}

    def handler(req: httpx.Request):
        sent["secret"] = req.headers.get("x-forge-debug-secret")
        return httpx.Response(200, content='data: {"type":"watch_ready"}\n\n', headers={"content-type": "text/event-stream"})

    fake_app(monkeypatch, handler)
    resp = await debug_watch(project.id, AgentWatch(app_url="http://localhost:3000", graph=GRAPH), _User(), None)
    events = await drain(resp)
    assert [e["type"] for e in events] == ["platform_map", "watch_ready"]
    assert events[0]["tools"] == {"close_ticket": "t1", "lookup": "t2"} and events[0]["kinds"]["system_prompt"] == ["sp"]
    assert sent["secret"], "the platform sends the key"


@pytest.mark.asyncio
async def test_the_watch_without_a_drawing_still_streams(project, monkeypatch):
    from routers.agent_builder import debug_watch
    from schemas.agent_builder import AgentWatch

    ensure_debug_secret(__import__("pathlib").Path(project.output_dir))
    fake_app(monkeypatch, lambda req: httpx.Response(200, content='data: {"type":"watch_ready"}\n\n'))
    events = await drain(await debug_watch(project.id, AgentWatch(app_url="http://localhost:3000"), _User(), None))
    assert [e["type"] for e in events] == ["watch_ready"]


def test_there_is_no_way_to_send_a_message_from_the_builder():
    """Watching is read-only: the builder cannot make the app's assistant do anything."""
    import routers.agent_builder as r

    paths = {getattr(route, "path", "") for route in r.router.routes}
    assert not any(p.endswith("/debug-run") for p in paths)
    assert any(p.endswith("/debug/watch") for p in paths) and any(p.endswith("/debug/status") for p in paths)
