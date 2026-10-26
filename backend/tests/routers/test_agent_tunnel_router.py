"""The tunnel's endpoints and how Watch live uses them (routers/agent_tunnel.py, the debug routes in routers/agent_builder.py).

Driven like the other router tests: the function itself, the project lookup stubbed, a temp tunnel folder, the app faked at the HTTP
layer. Pinned: only a member of the project can ask for a code, see the tunnel or remove it; redeeming a code is public but the
code is the credential, a refusal is a plain status with a sentence, and the client's address is the one the proxy wrote; the
connector is served without any secret in it; and Watch live's status and stream go through the tunnel when asked to, with the
secret the connector made, never through an address a person typed.
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

PID = uuid.UUID("11111111-2222-3333-4444-555555555555")
SECRET = "z" * 43
REAL_CLIENT = httpx.AsyncClient


def key(seed: int = 1) -> str:
    return "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes([seed]) * 32).decode()


class _User:
    id = "u-1"


class _Colleague:
    id = "u-2"


class _Rows:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class _Db:
    def __init__(self, row=None):
        self.row = row

    async def execute(self, _q):
        return _Rows(self.row)


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_TUNNEL_DIR", str(tmp_path))
    monkeypatch.setenv("FORGE_TUNNEL_PUBLIC_HOST", "13.212.213.53")
    monkeypatch.setenv("FORGE_TUNNEL_HOST", "127.0.0.1")
    (tmp_path / "host_key.pub").write_text(key(9) + " root@t\n", encoding="utf-8")
    agent_tunnel._bad.clear()
    proj = SimpleNamespace(id=PID, output_dir=None, org_id=uuid.uuid4())

    async def fake_get(project_id, user, db):
        if str(project_id) != str(PID):
            raise HTTPException(status_code=404, detail="Project not found")
        return proj

    monkeypatch.setattr("routers.agent_tunnel.get_project_with_auth", fake_get)
    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    return tmp_path


def fake_app(monkeypatch, handler):
    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return REAL_CLIENT(*a, **kw)

    monkeypatch.setattr(agent_debug.httpx, "AsyncClient", factory)


async def pair_now(ip="5.6.7.8", k=None, port=3001, secret=SECRET):
    from routers.agent_tunnel import PairRequest, redeem

    code = (await __import__("routers.agent_tunnel", fromlist=["x"]).tunnel_pair(PID, _User(), _Db()))["code"]
    req = SimpleNamespace(headers={"x-forwarded-for": ip}, client=SimpleNamespace(host="172.18.0.1"))
    return await redeem(PairRequest(code=code, publicKey=k or key(), appPort=port, secret=secret, label="Ana laptop"), req)


# ── the builder's side ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_member_sees_the_tunnel_asks_for_a_code_and_removes_the_computer(server):
    from routers.agent_tunnel import tunnel_pair, tunnel_revoke, tunnel_state

    assert (await tunnel_state(PID, _User(), _Db()))["registered"] is False
    code = await tunnel_pair(PID, _User(), _Db())
    assert len(code["code"]) == 9 and code["expiresAt"] > 0
    await pair_now()
    state = await tunnel_state(PID, _User(), _Db())
    assert state["registered"] is True and state["clientIp"] == "5.6.7.8" and SECRET not in json.dumps(state)
    assert (await tunnel_revoke(PID, _User(), _Db())) == {"removed": True}
    assert (await tunnel_state(PID, _User(), _Db()))["registered"] is False


@pytest.mark.asyncio
async def test_someone_who_is_not_a_member_gets_nothing(server):
    from routers.agent_tunnel import tunnel_pair, tunnel_revoke, tunnel_state

    other = uuid.uuid4()
    for call in (tunnel_state, tunnel_pair, tunnel_revoke):
        with pytest.raises(HTTPException) as e:
            await call(other, _User(), _Db())
        assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_the_state_says_where_the_app_is_hosted_when_the_platform_knows(server):
    from routers.agent_tunnel import tunnel_state

    row = SimpleNamespace(target="vercel", url="https://my-app.vercel.app", deployment_url=None, environment="production")
    out = await tunnel_state(PID, _User(), _Db(row))
    assert out["hosted"] == {"vercel": {"url": "https://my-app.vercel.app", "environment": "production"}}


@pytest.mark.asyncio
async def test_a_platform_on_the_builders_own_computer_says_there_is_nothing_to_connect(monkeypatch):
    from routers.agent_tunnel import tunnel_pair, tunnel_state

    monkeypatch.delenv("FORGE_TUNNEL_DIR", raising=False)
    proj = SimpleNamespace(id=PID, output_dir=None)

    async def fake_get(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.agent_tunnel.get_project_with_auth", fake_get)
    assert (await tunnel_state(PID, _User(), _Db()))["enabled"] is False
    with pytest.raises(HTTPException) as e:
        await tunnel_pair(PID, _User(), _Db())
    assert e.value.status_code == 409 and "your own computer" in e.value.detail


# ── the connector's side ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redeeming_gives_where_to_connect_and_records_the_address_the_proxy_wrote(server):
    out = await pair_now(ip="93.184.216.34")
    assert out["sshHost"] == "13.212.213.53" and out["sshUser"] == "tunnel" and out["hostKey"] == key(9)
    assert out["yourAddress"] == "93.184.216.34" and agent_tunnel.get(str(PID))["clientIp"] == "93.184.216.34"


@pytest.mark.asyncio
async def test_where_to_connect_is_served_without_signing_in_and_a_missing_service_says_so(server, monkeypatch):
    from routers.agent_tunnel import tunnel_info

    out = await tunnel_info()
    assert out["sshHost"] == "13.212.213.53" and out["hostKey"] == key(9) and "secret" not in json.dumps(out)
    monkeypatch.delenv("FORGE_TUNNEL_PUBLIC_HOST")
    with pytest.raises(HTTPException) as e:
        await tunnel_info()
    assert e.value.status_code == 503 and "public address" in e.value.detail


@pytest.mark.asyncio
async def test_a_forged_forwarded_for_cannot_pose_as_another_address(server):
    from routers.agent_tunnel import _client_ip

    req = SimpleNamespace(headers={"x-forwarded-for": "1.1.1.1, 203.0.113.9"}, client=SimpleNamespace(host="172.18.0.1"))
    assert _client_ip(req) == "203.0.113.9", "the last entry is the one the proxy wrote; earlier ones came from the client"
    assert _client_ip(SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.2"))) == "10.0.0.2"
    assert _client_ip(SimpleNamespace(headers={}, client=None)) == ""


@pytest.mark.asyncio
async def test_each_refusal_is_a_status_and_a_sentence(server):
    from routers.agent_tunnel import PairRequest, redeem

    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="9.9.9.9"))
    with pytest.raises(HTTPException) as bad_code:
        await redeem(PairRequest(code="AAAA-BBBB", publicKey=key(), appPort=3000, secret=SECRET), req)
    assert bad_code.value.status_code == 404 and "not valid, or it has expired" in bad_code.value.detail
    from routers.agent_tunnel import tunnel_pair

    code = (await tunnel_pair(PID, _User(), _Db()))["code"]
    with pytest.raises(HTTPException) as bad_key:
        await redeem(PairRequest(code=code, publicKey='command="x" ' + key(), appPort=3000, secret=SECRET), req)
    assert bad_key.value.status_code == 400 and "ed25519" in bad_key.value.detail


def test_the_request_model_refuses_oversized_input_before_anything_looks_at_it():
    from pydantic import ValidationError

    from routers.agent_tunnel import PairRequest

    with pytest.raises(ValidationError):
        PairRequest(code="A" * 33, publicKey=key(), appPort=1, secret=SECRET)
    with pytest.raises(ValidationError):
        PairRequest(code="AAAA-BBBB", publicKey="k" * 201, appPort=1, secret=SECRET)
    with pytest.raises(ValidationError):
        PairRequest(code="AAAA-BBBB", publicKey=key(), appPort=1, secret="s" * 101)


@pytest.mark.asyncio
async def test_the_connector_is_served_and_holds_no_secret():
    from routers.agent_tunnel import connector

    r = await connector()
    body = r.body.decode()
    assert r.media_type.startswith("text/javascript") and 'filename="ttf-watch-connect.mjs"' in r.headers["content-disposition"]
    assert "ttf-watch-connect" in body and "reverse SSH tunnel" in body
    assert "ANTHROPIC" not in body and "SECRET_KEY" not in body and "BEGIN OPENSSH" not in body


# ── Watch live through the tunnel ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_through_the_tunnel_uses_the_platforms_own_address_and_the_connectors_secret(server, monkeypatch):
    from routers.agent_builder import debug_status

    out = await pair_now()
    port = out["port"]
    monkeypatch.setattr(agent_tunnel, "listener_open", lambda p, timeout=1.5: True)
    seen = []

    def handler(req: httpx.Request):
        seen.append((str(req.url), req.headers.get("x-forge-debug-secret")))
        return httpx.Response(200, json={"agents": [{"id": "support", "name": "Support", "enabled": True}]})

    fake_app(monkeypatch, handler)
    res = await debug_status(PID, "tunnel", _User(), None)
    assert res["ok"] is True and res["agents"][0]["id"] == "support"
    assert seen == [(f"http://127.0.0.1:{port}/api/agent/debug", SECRET)]


@pytest.mark.asyncio
async def test_status_through_the_tunnel_before_any_computer_is_paired_says_how(server):
    from routers.agent_builder import debug_status

    res = await debug_status(PID, "tunnel", _User(), None)
    assert res["ok"] is False and res["reason"] == agent_debug.NOT_PAIRED


@pytest.mark.asyncio
async def test_the_stream_through_the_tunnel_passes_the_events_and_a_typed_address_is_still_refused(server, monkeypatch):
    from routers.agent_builder import debug_watch
    from schemas.agent_builder import AgentWatch

    await pair_now()
    fake_app(monkeypatch, lambda req: httpx.Response(200, content=b'data: {"type":"watch_ready"}\n\n'))
    resp = await debug_watch(PID, AgentWatch(app_url="tunnel"), _User(), None)
    raw = b"".join([c async for c in resp.body_iterator]).decode()
    assert 'watch_ready' in raw

    unpaired = await debug_watch(PID, AgentWatch(app_url="Tunnel"), _User(), None)
    agent_tunnel.revoke(str(PID), user_id=_User.id)
    again = b"".join([c async for c in (await debug_watch(PID, AgentWatch(app_url="tunnel"), _User(), None)).body_iterator]).decode()
    assert agent_debug.NOT_PAIRED in again, "with the computer removed it says how to connect, instead of reaching for an address"
    assert unpaired is not None


@pytest.mark.asyncio
async def test_a_colleague_cannot_re_pair_or_remove_a_computer_that_is_offline_but_an_org_admin_can(server, monkeypatch):
    from routers.agent_tunnel import tunnel_pair, tunnel_revoke

    await pair_now()                                              # registered by u-1; nothing is listening, so it is offline
    seen = []

    async def not_admin(org_id, user, db, min_role=None, request=None):
        seen.append((user.id, min_role.value))
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    monkeypatch.setattr("services.org_access.require_org_member", not_admin)
    for call in (tunnel_pair, tunnel_revoke):
        with pytest.raises(HTTPException) as e:
            await call(PID, _Colleague(), _Db())
        assert e.value.status_code == 403 and "colleague" in e.value.detail
    assert agent_tunnel.get(str(PID))["publicKey"] == key()
    assert (await tunnel_pair(PID, _User(), _Db()))["code"], "the person who registered it may ask again"

    async def admin_only(org_id, user, db, min_role=None, request=None):
        seen.append((user.id, min_role.value))

    monkeypatch.setattr("services.org_access.require_org_member", admin_only)
    assert (await tunnel_pair(PID, _Colleague(), _Db()))["code"]
    assert (await tunnel_revoke(PID, _Colleague(), _Db())) == {"removed": True}
    assert seen and seen[0] == ("u-2", "admin")


@pytest.mark.asyncio
async def test_a_member_who_is_not_an_admin_is_refused_when_the_admin_check_says_no(server, monkeypatch):
    from routers.agent_tunnel import tunnel_revoke

    await pair_now()

    async def not_admin(org_id, user, db, min_role=None, request=None):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    monkeypatch.setattr("services.org_access.require_org_member", not_admin)
    with pytest.raises(HTTPException) as e:
        await tunnel_revoke(PID, _Colleague(), _Db())
    assert e.value.status_code == 403 and "colleague" in e.value.detail


def test_the_builders_tunnel_routes_need_the_agents_feature_and_the_connectors_routes_do_not():
    from routers.agent_tunnel import router

    def gated(route):
        return any(getattr(d.call, "__name__", "") == "feature_gate_agents" for d in route.dependant.dependencies)

    by_path = {(r.path, tuple(sorted(r.methods))): gated(r) for r in router.routes}
    builder = {k: v for k, v in by_path.items() if k[0].startswith("/api/projects/")}
    public = {k: v for k, v in by_path.items() if k[0].startswith("/api/tunnel/")}
    assert len(builder) == 3 and all(builder.values()), builder
    assert len(public) == 3 and not any(public.values()), public
