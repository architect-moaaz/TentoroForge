"""Watching a running app live, the platform's side.

What is pinned: the secret is made once, kept out of git and never sent anywhere but this computer; the platform
says in plain words why a live run cannot start (app not running, app too old, production build); the app's event
stream is passed through untouched; the install brings the route, the key and the way past the sign-in guard.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from services import agent_debug
from services.agent_debug import DebugError, clean_app_url, ensure_debug_secret, read_debug_secret, status
from services.agent_runtime_install import install_agent_runtime

from tests.services.test_agent_runtime_install import graph, make_app, node, sample_graph


REAL_CLIENT = httpx.AsyncClient  # captured before any patching, so a second mock replaces the first


def mock_app(monkeypatch, handler):
    """Make every httpx client in the service talk to ``handler`` instead of the network."""
    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return REAL_CLIENT(*a, **kw)

    monkeypatch.setattr(agent_debug.httpx, "AsyncClient", factory)


# ── the secret ────────────────────────────────────────────────────────────

def test_the_secret_is_made_once_and_kept_out_of_git(tmp_path):
    first = ensure_debug_secret(tmp_path)
    assert len(first) >= 32 and read_debug_secret(tmp_path) == first
    assert ensure_debug_secret(tmp_path) == first  # not changed on the next install
    assert ".forge-debug-secret" in (tmp_path / ".gitignore").read_text().split()
    ensure_debug_secret(tmp_path)
    assert (tmp_path / ".gitignore").read_text().split().count(".forge-debug-secret") == 1


def test_no_secret_reads_as_none(tmp_path):
    assert read_debug_secret(tmp_path) is None


# ── where the secret may be sent ──────────────────────────────────────────

@pytest.mark.parametrize("url", ["http://localhost:3000", "http://127.0.0.1:3001/", "https://app.localhost:8443", "http://[::1]:3000"])
def test_only_this_computer_is_allowed(url):
    assert clean_app_url(url).startswith("http")


@pytest.mark.parametrize("url", ["", "localhost:3000", "ftp://localhost", "http://example.com", "http://192.168.1.5:3000",
                                 "http://localhost.evil.com", "http://evil.com/localhost", "javascript:alert(1)"])
def test_anywhere_else_is_refused(url):
    with pytest.raises(DebugError):
        clean_app_url(url)


def test_the_address_is_cut_down_to_scheme_and_host():
    assert clean_app_url("http://localhost:3000/some/path?x=1") == "http://localhost:3000"


# ── is it working? ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_says_the_app_can_be_watched(monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.path, req.url.params.get("users"), req.headers.get("x-forge-debug-secret")))
        if req.url.params.get("users"):
            raise AssertionError("the people of the app are no longer asked for")
        return httpx.Response(200, json={"debug": True, "agents": [{"id": "app_assistant", "name": "Assistant", "enabled": True}]})

    mock_app(monkeypatch, handler)
    r = await status("http://localhost:3000/", "s3cret")
    assert r["ok"] is True and r["agents"][0]["id"] == "app_assistant" and "users" not in r
    assert all(s[2] == "s3cret" for s in seen), "the key goes with every request"


@pytest.mark.asyncio
async def test_status_explains_each_way_it_cannot_work(monkeypatch):
    assert "no live-run key" in (await status("http://localhost:3000", None))["reason"]

    mock_app(monkeypatch, lambda req: httpx.Response(404, json={"error": "Not found."}))
    off = await status("http://localhost:3000", "k")
    assert off["ok"] is False and "Apply the agent once" in off["reason"] and "development mode" in off["reason"]

    def down(req):
        raise httpx.ConnectError("refused")

    mock_app(monkeypatch, down)
    gone = await status("http://localhost:3000", "k")
    assert gone["ok"] is False and "Is it running" in gone["reason"]


# ── the stream ────────────────────────────────────────────────────────────

async def collect(gen) -> list[dict]:
    raw = b"".join([c async for c in gen]).decode()
    return [json.loads(line[6:]) for line in raw.split("\n") if line.startswith("data: ")]


# ── the install ───────────────────────────────────────────────────────────

MIDDLEWARE = 'export const config = {\n  matcher: ["/((?!api/auth|_next|favicon.ico|login|signup|.*\\\\..*).*)"],\n};\n'


def test_the_install_brings_the_route_the_key_and_the_way_past_the_sign_in_guard(tmp_path):
    project, app = make_app(tmp_path)
    (app / "src" / "middleware.ts").write_text(MIDDLEWARE, encoding="utf-8")
    install_agent_runtime(project, graphs=[sample_graph()])
    assert (app / "src" / "app" / "api" / "agent" / "debug" / "route.ts").is_file()
    assert (app / "src" / "lib" / "agents" / "debug.ts").is_file()
    assert read_debug_secret(app)
    mw = (app / "src" / "middleware.ts").read_text(encoding="utf-8")
    assert mw.count("api/agent/debug") == 1 and "(?!api/auth|api/agent/debug|" in mw
    install_agent_runtime(project)  # again: still once, and the key does not change
    key = read_debug_secret(app)
    install_agent_runtime(project)
    assert (app / "src" / "middleware.ts").read_text(encoding="utf-8").count("api/agent/debug") == 1
    assert read_debug_secret(app) == key


def test_an_app_with_no_middleware_is_left_alone(tmp_path):
    project, app = make_app(tmp_path)
    r = install_agent_runtime(project, graphs=[sample_graph()])
    assert r["installed"] and not (app / "src" / "middleware.ts").exists()


# ── the wrong address ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_refused_address_points_to_this_projects_app_running_elsewhere(monkeypatch):
    def handler(req: httpx.Request):
        # only the app on 3001 knows this key; every other answers a wrong key as nothing at all
        if req.url.port == 3001 and req.headers.get("x-forge-debug-secret") == "mine":
            if req.url.params.get("users"):
                return httpx.Response(200, json={"users": []})
            return httpx.Response(200, json={"agents": []})
        return httpx.Response(404, json={"error": "Not found."})

    mock_app(monkeypatch, handler)
    r = await status("http://localhost:3000", "mine")
    assert r["ok"] is False and r["suggestedUrl"] == "http://localhost:3001"
    assert "http://localhost:3001" in r["reason"] and "this project's key" in r["reason"]
    assert (await status("http://localhost:3001", "mine"))["ok"] is True


@pytest.mark.asyncio
async def test_with_the_app_nowhere_the_reason_is_the_plain_one(monkeypatch):
    mock_app(monkeypatch, lambda req: httpx.Response(404, json={"error": "Not found."}))
    r = await status("http://localhost:3000", "mine")
    assert r["ok"] is False and "suggestedUrl" not in r and "another project's app" in r["reason"]


@pytest.mark.asyncio
async def test_an_app_that_is_down_is_reported_down_and_not_as_a_wrong_address(monkeypatch):
    def down(req):
        raise httpx.ConnectError("refused")

    mock_app(monkeypatch, down)
    r = await status("http://localhost:3000", "mine")
    assert r["ok"] is False and "suggestedUrl" not in r and "Is it running" in r["reason"]


# ── watching the real chats live ──────────────────────────────────────────

from services.agent_debug import flow_map, watch_stream  # noqa: E402


def test_the_map_says_which_box_each_tool_and_step_belongs_to():
    g = graph(
        node("sp", "system_prompt", "P", {"prompt": "x"}),
        node("t1", "tool", "Lookup", {"tool_name": "look_up", "tool_type": "function"}),
        node("t2", "tool", "Second", {"tool_name": "look_up", "tool_type": "function"}),
        node("g1", "guardrail", "Guard", {}), node("g2", "guardrail", "Guard 2", {}),
        node("m", "memory", "Mem", {}), node("h", "human_handoff", "Handoff", {}),
    )
    m = flow_map(g)
    assert m["tools"] == {"look_up": "t1", "look_up_2": "t2"}, "named exactly as the compiler names them, even a repeat"
    assert set(m["toolInfo"]) == {"look_up", "look_up_2", "request_human"}, "and what each accepts (the handoff box adds its own tool), so a call's input can be checked"
    assert m["toolInfo"]["look_up"]["inputSchema"]["type"] == "object"
    assert m["kinds"] == {"system_prompt": ["sp"], "guardrail": ["g1", "g2"], "memory": ["m"], "human_handoff": ["h"]}


@pytest.mark.asyncio
async def test_the_watch_passes_the_apps_feed_through_as_it_arrives(monkeypatch):
    feed = 'data: {"type":"watch_ready"}\n\ndata: {"type":"run_start","runId":"r1"}\n\n'
    seen = {}

    def handler(req: httpx.Request):
        seen["watch"] = req.url.params.get("watch")
        seen["secret"] = req.headers.get("x-forge-debug-secret")
        return httpx.Response(200, content=feed, headers={"content-type": "text/event-stream"})

    mock_app(monkeypatch, handler)
    events = await collect(watch_stream("http://localhost:3000", "k"))
    assert [e["type"] for e in events] == ["watch_ready", "run_start"]
    assert seen == {"watch": "1", "secret": "k"}


@pytest.mark.asyncio
async def test_the_watch_says_in_one_event_why_it_cannot_start(monkeypatch):
    assert "this computer" in (await collect(watch_stream("http://example.com", "k")))[0]["message"]
    assert "no live-run key" in (await collect(watch_stream("http://localhost:3000", None)))[0]["message"]

    mock_app(monkeypatch, lambda req: httpx.Response(404, json={"error": "Not found."}))
    assert "another project's app" in (await collect(watch_stream("http://localhost:3000", "k")))[0]["message"]

    def down(req):
        raise httpx.ConnectError("refused")

    mock_app(monkeypatch, down)
    assert "Is it running" in (await collect(watch_stream("http://localhost:3000", "k")))[0]["message"]
