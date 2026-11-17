"""The insights endpoint (routers/agent_builder.py::agent_insights): who may ask, how the connected app is chosen, and that it always
answers with `{ok, insights}` or `{ok, reason}` instead of raising for an app that cannot be reached.

Driven like the tunnel router tests: the function itself, the project lookup stubbed, a temp tunnel folder, a temp app folder with its own
debug secret, the app faked at the HTTP layer.
"""
from __future__ import annotations

import base64
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

import models  # noqa: F401  (register every model before test_db.create_all)
from services import agent_debug, agent_tunnel
from tests.services.test_agent_insights import good

PID = uuid.UUID("11111111-2222-3333-4444-555555555555")
TUNNEL_SECRET = "z" * 43
APP_SECRET = "app-secret-in-the-projects-own-folder"
REAL_CLIENT = httpx.AsyncClient


class _User:
    id = "u-1"


def key(seed: int = 1) -> str:
    return "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes([seed]) * 32).decode()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    tdir = tmp_path / "tunnel"
    tdir.mkdir()
    monkeypatch.setenv("FORGE_TUNNEL_DIR", str(tdir))
    monkeypatch.setenv("FORGE_TUNNEL_PUBLIC_HOST", "13.212.213.53")
    monkeypatch.setenv("FORGE_TUNNEL_HOST", "127.0.0.1")
    (tdir / "host_key.pub").write_text(key(9) + " root@t\n", encoding="utf-8")
    agent_tunnel._bad.clear()
    app = tmp_path / "out" / "app"
    app.mkdir(parents=True)
    (app / agent_debug.SECRET_FILE).write_text(APP_SECRET + "\n", encoding="utf-8")
    proj = SimpleNamespace(id=PID, output_dir=str(tmp_path / "out"))

    async def fake_get(project_id, user, db):
        if str(project_id) != str(PID):
            raise HTTPException(status_code=404, detail="Project not found")
        return proj

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    monkeypatch.setattr("services.agent_runtime_install.resolve_roots", lambda out: (out, app))
    return SimpleNamespace(proj=proj, app=app)


def fake_app(monkeypatch, handler):
    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return REAL_CLIENT(*a, **kw)

    monkeypatch.setattr(agent_debug.httpx, "AsyncClient", factory)


def pair():
    agent_tunnel.pair(agent_tunnel.new_pairing(str(PID))["code"], key(), 3001, TUNNEL_SECRET, client_ip="5.6.7.8", label="laptop")


async def call(app_url="tunnel", days=7, agent_id="", pid=PID):
    from routers.agent_builder import agent_insights

    return await agent_insights(pid, app_url, days, agent_id, _User(), None)


@pytest.mark.asyncio
async def test_through_the_tunnel_it_answers_ok_with_the_enriched_insights(env, monkeypatch):
    pair()
    monkeypatch.setattr(agent_tunnel, "listener_open", lambda p, timeout=1.5: True)
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.path, req.url.params["days"], req.url.params.get("agent"), req.headers["x-forge-debug-secret"]))
        return httpx.Response(200, json=good())

    fake_app(monkeypatch, handler)
    out = await call("tunnel", 30, "support")
    assert out["ok"] is True and out["insights"]["cost"]["estimatedUsd"] == pytest.approx(2.70)
    assert out["insights"]["tips"] == [] and out["insights"]["quality"]["thumbsUp"]["count"] == 8
    assert seen == [("/api/agent/insights", "30", "support", TUNNEL_SECRET)]
    assert TUNNEL_SECRET not in json.dumps(out) and APP_SECRET not in json.dumps(out)


@pytest.mark.asyncio
async def test_a_typed_localhost_address_uses_the_projects_own_secret_not_the_tunnels(env, monkeypatch):
    pair()
    seen = []
    fake_app(monkeypatch, lambda req: (seen.append((str(req.url.host), req.headers["x-forge-debug-secret"])), httpx.Response(200, json=good()))[1])
    out = await call("http://localhost:3000")
    assert out["ok"] is True and seen == [("localhost", APP_SECRET)]


@pytest.mark.asyncio
async def test_a_computer_that_was_never_paired_is_a_reason_not_an_error(env):
    out = await call("tunnel")
    assert out == {"ok": False, "reason": agent_debug.NOT_PAIRED}


@pytest.mark.asyncio
async def test_a_tunnel_that_is_down_is_a_reason(env):
    pair()
    assert (await call("Tunnel")) == {"ok": False, "reason": agent_debug.TUNNEL_DOWN}


@pytest.mark.asyncio
async def test_an_address_off_this_computer_is_refused_with_a_reason_and_nothing_is_sent(env, monkeypatch):
    def handler(req):
        raise AssertionError("must not be called")

    fake_app(monkeypatch, handler)
    out = await call("http://10.0.0.5:3000")
    assert out["ok"] is False and "this computer" in out["reason"]


@pytest.mark.asyncio
async def test_an_app_without_the_route_gets_the_apply_again_sentence(env, monkeypatch):
    fake_app(monkeypatch, lambda req: httpx.Response(404, json={"error": "Not found."}) if req.url.path.endswith("insights") else httpx.Response(200, json={"agents": []}))
    out = await call("http://localhost:3000")
    assert out["ok"] is False and "does not record insights yet" in out["reason"]


@pytest.mark.asyncio
async def test_nothing_running_is_a_reason(env, monkeypatch):
    def refused(req):
        raise httpx.ConnectError("no")

    fake_app(monkeypatch, refused)
    out = await call("http://localhost:3000")
    assert out["ok"] is False and "Is it running?" in out["reason"]


@pytest.mark.asyncio
async def test_a_project_that_was_never_built_says_so_for_a_typed_address(env, monkeypatch):
    env.proj.output_dir = None
    with pytest.raises(HTTPException) as e:
        await call("http://localhost:3000")
    assert e.value.status_code == 400 and "not been built yet" in e.value.detail


@pytest.mark.asyncio
async def test_someone_who_is_not_a_member_gets_nothing(env):
    with pytest.raises(HTTPException) as e:
        await call("tunnel", pid=uuid.uuid4())
    assert e.value.status_code == 404


def test_the_route_is_declared_before_the_agent_id_route():
    from routers.agent_builder import router

    paths = [r.path for r in router.routes if "GET" in getattr(r, "methods", set())]
    i = paths.index("/api/projects/{project_id}/agent-definitions/insights")
    assert i < paths.index("/api/projects/{project_id}/agent-definitions/{agent_id}")

