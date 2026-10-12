"""The builder's live run, through the platform's two endpoints.

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


def run_request(**over):
    from schemas.agent_builder import AgentDebugRun

    base = {"app_url": "http://localhost:3000", "message": "close ticket 7", "as_user_id": "u9", "session_id": "s1"}
    return AgentDebugRun(**{**base, **over})


@pytest.mark.asyncio
async def test_status_uses_the_apps_own_key(project, monkeypatch):
    from routers.agent_builder import debug_status

    secret = ensure_debug_secret(__import__("pathlib").Path(project.output_dir))
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.headers.get("x-forge-debug-secret"))
        if req.url.params.get("users"):
            return httpx.Response(200, json={"users": [{"id": "u9", "name": "Lena", "role": "Support"}]})
        return httpx.Response(200, json={"agents": [{"id": "support", "name": "Support Bot", "enabled": True}]})

    fake_app(monkeypatch, handler)
    out = await debug_status(project.id, "http://localhost:3000", _User(), None)
    assert out["ok"] is True and out["users"][0]["name"] == "Lena"
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
async def test_a_run_sends_the_installed_agent_when_not_asked_for_the_draft(project, monkeypatch):
    from routers.agent_builder import debug_run

    ensure_debug_secret(__import__("pathlib").Path(project.output_dir))
    sent = {}

    def handler(req: httpx.Request):
        sent["payload"] = json.loads(req.content)
        return httpx.Response(200, content='data: {"type":"done","t":3}\n\n', headers={"content-type": "text/event-stream"})

    fake_app(monkeypatch, handler)
    resp = await debug_run(project.id, "support", run_request(graph=GRAPH), _User(), None)
    events = await drain(resp)
    assert events == [{"type": "done", "t": 3}]
    p = sent["payload"]
    assert p["agentId"] == "support" and p["asUserId"] == "u9" and p["sessionId"] == "s1" and p["allowChanges"] is False
    assert "config" not in p, "the installed agent runs; no draft was sent"


@pytest.mark.asyncio
async def test_a_run_of_the_draft_compiles_it_here_and_says_what_is_off(project, monkeypatch):
    from routers.agent_builder import debug_run

    ensure_debug_secret(__import__("pathlib").Path(project.output_dir))
    sent = {}

    def handler(req: httpx.Request):
        sent["payload"] = json.loads(req.content)
        return httpx.Response(200, content='data: {"type":"done","t":1}\n\n', headers={"content-type": "text/event-stream"})

    fake_app(monkeypatch, handler)
    resp = await debug_run(project.id, "support", run_request(use_draft=True, allow_changes=True, graph=GRAPH), _User(), None)
    events = await drain(resp)
    assert events[0]["type"] == "platform_note" and any("no code" in w for w in events[0]["warnings"])
    assert events[-1] == {"type": "done", "t": 1}
    cfg = sent["payload"]["config"]
    assert cfg["systemPrompt"].startswith("You help customers.")
    assert {t["name"]: t.get("confirm", False) for t in cfg["tools"]} == {"close_ticket": True, "lookup": False}
    assert sent["payload"]["allowChanges"] is True and sent["payload"]["agentId"] == "support"


@pytest.mark.asyncio
async def test_a_run_against_an_app_that_is_down_is_one_error_the_screen_can_show(project, monkeypatch):
    from routers.agent_builder import debug_run

    ensure_debug_secret(__import__("pathlib").Path(project.output_dir))

    def down(req):
        raise httpx.ConnectError("refused")

    fake_app(monkeypatch, down)
    events = await drain(await debug_run(project.id, "support", run_request(), _User(), None))
    assert len(events) == 1 and events[0]["type"] == "error" and "Is it running" in events[0]["message"]
