"""The routes: the builder's key and summary, and the public ingest route an app posts to. Through the real app, a real project and real sign-in."""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from database import async_session
from models.agent_insights import AgentInsightKey, agent_turn_events
from services import agent_insights_bus as bus_mod
from services import agent_insights_ingest as ingest
from services import agent_insights_keys as keys
from services.agent_insights_bus import MemoryBus, unpack
from services.agent_insights_worker import InsightsWorker
from tests.insights_stream_helpers import rating, turn

NOW = datetime.now(timezone.utc)


from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _the_clock_starts_with_each_test():
    # One fixed time per test (a repeated turn must look the same), taken when the test runs, not when the file is
    # loaded: in a long run "10 minutes ahead" had slid into the past by then and was no longer rejected.
    global NOW
    NOW = datetime.now(timezone.utc)


def t(i, minutes_ago=2, **kw):
    return turn(i, NOW - timedelta(minutes=minutes_ago), **kw)


@pytest_asyncio.fixture
async def project(auth_client, org_id):
    r = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Insights App"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest_asyncio.fixture(autouse=True)
async def clean(monkeypatch):
    monkeypatch.setenv("FORGE_INSIGHTS_SUMMARY_CACHE_S", "0")   # every summary read here must see the latest events
    monkeypatch.setenv("FORGE_INSIGHTS_PEOPLE_CACHE", "0")      # (and the people numbers are counted afresh: there is no worker refreshing them here)
    bus_mod.use_bus(None)           # no Redis unless a test says so
    keys.forget_cache()
    ingest.RATE_LIMITER._b.clear()
    ingest.AUTH_FAILURES._b.clear()
    ingest.DROPPED.pending.clear()
    yield
    bus_mod.reset_bus()
    keys.forget_cache()


def base(project) -> str:
    return f"/api/projects/{project['id']}/agent-definitions/insights"


async def make_key(auth_client, project) -> str:
    r = await auth_client.post(base(project) + "/key")
    assert r.status_code == 200, r.text
    return r.json()["key"]


async def post(client, key, events=None, *, raw: bytes | None = None, headers=None, schema=1):
    body = raw if raw is not None else json.dumps({"schema": schema, "events": events}).encode()
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **(headers or {})}
    return await client.post("/api/insights/ingest", content=body, headers=h)


@pytest_asyncio.fixture
async def nobody(client):
    """A client with no sign-in at all: what an app server is."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# --- the key ----------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_key_lifecycle_shown_once_hash_only_rotation_revokes_the_old_one(auth_client, nobody, project):
    r = await auth_client.get(base(project) + "/key")
    assert r.json() == {"exists": False, "prefix": None, "createdAt": None, "lastUsedAt": None, "eventsLast24h": 0}

    made = await auth_client.post(base(project) + "/key", headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "forge.example.com"})
    body = made.json()
    key = body["key"]
    assert key.startswith("fik_") and len(key) == 44 and body["prefix"] == key[:8]
    assert body["ingestUrl"] == "https://forge.example.com/api/insights/ingest"
    assert made.headers["cache-control"] == "no-store"
    # without the proxy headers it is the address the request came to
    assert (await auth_client.post(base(project) + "/key")).json()["ingestUrl"] == "http://test/api/insights/ingest"
    key = (await auth_client.post(base(project) + "/key")).json()["key"]      # (rotated twice more: only this one is live)

    got = await auth_client.get(base(project) + "/key")
    info = got.json()
    assert info["exists"] is True and info["prefix"] == key[:8] and info["createdAt"] and info["lastUsedAt"] is None
    assert key not in got.text and "key" not in info                           # never again

    # only the hash is stored, and only one key is live
    async with async_session() as s:
        rows = (await s.execute(select(AgentInsightKey))).scalars().all()
    assert len(rows) == 3 and sum(r.revoked_at is None for r in rows) == 1
    live = next(r for r in rows if r.revoked_at is None)
    assert live.key_hash == keys.hash_key(key) and live.prefix == key[:8]
    assert all(key not in str(v) for r in rows for v in (r.key_hash, r.prefix))

    assert (await post(nobody, key, [t(1)])).status_code == 202
    old = rows[0]
    assert old.revoked_at is not None
    # an old key is refused at once (the rotation forgot it in this process)
    first_key = body["key"]
    assert (await post(nobody, first_key, [t(2)])).status_code == 401
    assert (await post(nobody, key, [t(3)])).status_code == 202

    last = (await auth_client.get(base(project) + "/key")).json()
    assert last["lastUsedAt"] is not None and last["eventsLast24h"] == 2

    assert (await auth_client.delete(base(project) + "/key")).json() == {"removed": True}
    assert (await post(nobody, key, [t(4)])).status_code == 401
    assert (await auth_client.get(base(project) + "/key")).json()["exists"] is False


@pytest.mark.asyncio
async def test_only_a_member_of_the_project_can_use_the_key_and_summary_routes(auth_client, client, project):
    paths = [("get", base(project) + "/key"), ("post", base(project) + "/key"), ("delete", base(project) + "/key"),
             ("get", base(project) + "/summary?range=24h")]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        for method, path in paths:
            assert (await getattr(anon, method)(path)).status_code in (401, 403), path
    signup = await client.post("/api/auth/signup", json={"email": "stranger@example.com", "name": "S", "password": "Stranger123"})
    stranger = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as out:
        for method, path in paths:
            r = await getattr(out, method)(path, headers=stranger)
            assert r.status_code in (403, 404), (path, r.status_code)
    assert (await auth_client.get(base(project) + "/key")).status_code == 200


@pytest.mark.asyncio
async def test_the_existing_agent_routes_still_answer_beside_the_new_ones(auth_client, project):
    assert (await auth_client.get(f"/api/projects/{project['id']}/agent-definitions")).status_code == 200
    assert (await auth_client.get(base(project) + "/summary?range=bogus")).status_code == 422


# --- ingest: who and how big ------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_missing_wrong_or_malformed_key_is_401(auth_client, nobody, project):
    await make_key(auth_client, project)
    for header in (None, "Bearer nope", "Bearer fik_" + "a" * 40, "Basic abc", ""):
        h = {"Content-Type": "application/json"}
        if header is not None:
            h["Authorization"] = header
        r = await nobody.post("/api/insights/ingest", content=b"{}", headers=h)
        assert r.status_code == 401 and "key" in r.json()["error"]


def _wrong_key(i: int) -> str:
    return "fik_" + f"{i:040d}"


@pytest.mark.asyncio
async def test_wrong_keys_are_limited_per_caller_and_a_repeated_one_costs_no_lookup(auth_client, nobody, project, monkeypatch):
    key = await make_key(auth_client, project)
    assert (await post(nobody, key, [t(1)])).status_code == 202          # now a known good key
    clock = [0.0]
    monkeypatch.setattr(ingest, "AUTH_FAILURES", ingest.AuthFailureLimiter(rate=0.5, burst=3, clock=lambda: clock[0]))
    lookups = []
    real = keys.authenticate

    async def counting(token):
        lookups.append(token)
        return await real(token)

    monkeypatch.setattr(keys, "authenticate", counting)
    codes = [(await post(nobody, _wrong_key(i), [t(2)])).status_code for i in range(3)]
    assert codes == [401, 401, 401] and len(lookups) == 3
    r = await post(nobody, _wrong_key(99), [t(2)])                       # the caller used up its wrong keys: a new one is not even looked up
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and len(lookups) == 3
    assert (await post(nobody, _wrong_key(0), [t(2)])).status_code == 401   # one it has seen: answered from memory, still 401
    assert len(lookups) == 3
    assert (await post(nobody, key, [t(3)])).status_code == 202           # a good key is never slowed by the caller's bad ones
    clock[0] += 4                                                          # two seconds of refill is one more try
    assert (await post(nobody, _wrong_key(100), [t(2)])).status_code == 401 and len(lookups) == 4


@pytest.mark.asyncio
async def test_good_batches_never_use_up_the_wrong_key_allowance(auth_client, nobody, project, monkeypatch):
    key = await make_key(auth_client, project)
    monkeypatch.setattr(ingest, "AUTH_FAILURES", ingest.AuthFailureLimiter(rate=0.5, burst=2))
    monkeypatch.setattr(ingest, "RATE_LIMITER", ingest.KeyRateLimiter(rate=10_000, burst=10_000))
    codes = {(await post(nobody, key, [t(i)])).status_code for i in range(40)}
    assert codes == {202}
    assert (await post(nobody, _wrong_key(1), [t(1)])).status_code == 401  # the allowance is still whole


@pytest.mark.asyncio
async def test_an_accepted_batch_answers_202_with_counts_rejections_and_a_server_time(auth_client, nobody, project):
    key = await make_key(auth_client, project)
    bad = t(2)
    bad["status"] = "maybe"
    r = await post(nobody, key, [t(1), bad, t(1), rating(1, 1, NOW), {"type": "wat"}])
    assert r.status_code == 202
    b = r.json()
    assert b["accepted"] == 2 and b["duplicates"] == 1 and b["rejectedCount"] == 2
    assert [x["index"] for x in b["rejected"]] == [1, 4] and b["rejected"][0]["reason"] == "The 'status' must be ok, error or blocked."
    assert datetime.fromisoformat(b["serverTime"].replace("Z", "+00:00"))
    again = await post(nobody, key, [t(1)])                      # the same turn in a later request: known, not counted
    assert again.json() == {**again.json(), "accepted": 0, "duplicates": 1}
    async with async_session() as s:
        assert len((await s.execute(select(agent_turn_events))).all()) == 1


@pytest.mark.asyncio
async def test_gzip_bodies_work_and_a_bad_gzip_is_400(auth_client, nobody, project):
    key = await make_key(auth_client, project)
    raw = gzip.compress(json.dumps({"schema": 1, "events": [t(1), t(2)]}).encode())
    r = await post(nobody, key, raw=raw, headers={"Content-Encoding": "gzip"})
    assert r.status_code == 202 and r.json()["accepted"] == 2
    assert (await post(nobody, key, raw=b"junk", headers={"Content-Encoding": "gzip"})).status_code == 400


@pytest.mark.asyncio
async def test_size_limits_413_and_malformed_400(auth_client, nobody, project):
    key = await make_key(auth_client, project)
    assert (await post(nobody, key, [t(i) for i in range(501)])).status_code == 413
    assert (await post(nobody, key, [t(i) for i in range(500)])).status_code == 202
    assert (await post(nobody, key, raw=b" " * (ingest.MAX_BODY_BYTES + 5))).status_code == 413
    bomb = gzip.compress(b" " * (ingest.MAX_BODY_BYTES + 5))
    assert (await post(nobody, key, raw=bomb, headers={"Content-Encoding": "gzip"})).status_code == 413
    r = await post(nobody, key, raw=b"{oops")
    assert r.status_code == 400 and r.json()["error"] == "The body is not valid JSON."
    assert (await post(nobody, key, [], schema=7)).status_code == 400


@pytest.mark.asyncio
async def test_old_and_future_events_are_rejected_in_the_answer(auth_client, nobody, project):
    key = await make_key(auth_client, project)
    r = await post(nobody, key, [t(1, minutes_ago=91 * 24 * 60), t(2, minutes_ago=-10), t(3, minutes_ago=89 * 24 * 60), t(4, minutes_ago=-3)])
    b = r.json()
    assert b["accepted"] == 2 and [x["index"] for x in b["rejected"]] == [0, 1]
    assert "older than 90 days" in b["rejected"][0]["reason"] and "future" in b["rejected"][1]["reason"]


@pytest.mark.asyncio
async def test_the_per_key_rate_limit_answers_429_with_retry_after_and_is_counted_as_dropped(auth_client, nobody, project, monkeypatch):
    key = await make_key(auth_client, project)
    clock = [0.0]
    monkeypatch.setattr(ingest, "RATE_LIMITER", ingest.KeyRateLimiter(rate=200, burst=3, clock=lambda: clock[0]))
    codes = [(await post(nobody, key, [t(i)])).status_code for i in range(5)]
    assert codes == [202, 202, 202, 429, 429]
    r = await post(nobody, key, [t(9)])
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and "Slow down" in r.json()["error"]
    clock[0] += 1
    assert (await post(nobody, key, [t(10)])).status_code == 202
    other = await make_key(auth_client, project)                 # a new key is a new bucket
    assert other != key
    # the page is honest about the gap: 3 refused requests plus the invalid events below
    bad = t(11)
    bad["env"] = "x"
    await post(nobody, other, [bad, t(12)])
    out = (await auth_client.get(base(project) + "/summary?range=24h")).json()
    assert out["ok"] is True and out["insights"]["droppedEvents"] == 3 + 1


# --- ingest: where the events go --------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_without_redis_the_batch_is_applied_in_the_same_request(auth_client, nobody, project):
    key = await make_key(auth_client, project)
    await post(nobody, key, [t(1, user=1), t(2, user=2, status="error"), rating(1, -1, NOW)])
    out = (await auth_client.get(base(project) + "/summary?range=24h")).json()
    assert out["ok"], out
    ins = out["insights"]
    assert (ins["totals"]["turns"], ins["totals"]["errors"], ins["totals"]["down"]) == (2, 1, 1)
    assert ins["mode"] == "stream" and ins["users"]["active"] == 2 and ins["freshness"]["lastEventAt"]
    assert out["insights"]["tips"] is not None and ins["cost"]["estimatedUsd"] is not None


@pytest.mark.asyncio
async def test_with_a_stream_the_request_only_queues_and_the_worker_applies(auth_client, nobody, project):
    memory = MemoryBus()
    bus_mod.use_bus(memory)
    key = await make_key(auth_client, project)
    r = await post(nobody, key, [t(1), t(2), t(3, user=3)])
    assert r.status_code == 202 and r.json()["accepted"] == 3
    assert await memory.depth() == 1
    async with async_session() as s:
        assert (await s.execute(select(agent_turn_events))).all() == []        # nothing written by the request
    sent = unpack(next(iter(memory.entries.values())))
    assert sent["p"] == project["id"] and len(sent["e"]) == 3
    empty = (await auth_client.get(base(project) + "/summary?range=24h")).json()
    assert empty["ok"] is False and empty["reason"].startswith("No events yet")
    await InsightsWorker(consumer="w").drain(memory, timeout=5)
    ins = (await auth_client.get(base(project) + "/summary?range=24h")).json()["insights"]
    assert ins["totals"]["turns"] == 3 and ins["users"]["approximate"] is True


@pytest.mark.asyncio
async def test_when_redis_fails_mid_request_the_batch_is_applied_to_the_database_instead(auth_client, nobody, project):
    memory = MemoryBus()
    memory.fail_publish = True
    bus_mod.use_bus(memory)
    key = await make_key(auth_client, project)
    assert (await post(nobody, key, [t(1)])).status_code == 202
    assert (await auth_client.get(base(project) + "/summary?range=24h")).json()["insights"]["totals"]["turns"] == 1


@pytest.mark.asyncio
async def test_a_backed_up_stream_or_a_full_redis_answers_503_so_the_app_keeps_its_rows(auth_client, nobody, project, monkeypatch):
    memory = MemoryBus()
    bus_mod.use_bus(memory)
    key = await make_key(auth_client, project)
    monkeypatch.setattr(bus_mod, "MAX_BACKLOG", 2)
    assert (await post(nobody, key, [t(1)])).status_code == 202
    assert (await post(nobody, key, [t(2)])).status_code == 202
    r = await post(nobody, key, [t(3)])
    assert r.status_code == 503 and r.headers["retry-after"] == "5" and "retry" in r.json()["error"]

    async def full(payload):
        raise RuntimeError("OOM command not allowed when used memory > 'maxmemory'")

    monkeypatch.setattr(bus_mod, "MAX_BACKLOG", 100)
    monkeypatch.setattr(memory, "publish", full)
    assert (await post(nobody, key, [t(4)])).status_code == 503


@pytest.mark.asyncio
async def test_a_database_that_cannot_take_the_batch_answers_503(auth_client, nobody, project, monkeypatch):
    key = await make_key(auth_client, project)
    from services import agent_insights_store as store

    async def broken(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(store, "apply_events", broken)
    r = await post(nobody, key, [t(1)])
    assert r.status_code == 503 and r.headers["retry-after"] == "5"


@pytest.mark.asyncio
async def test_the_ingest_route_is_not_throttled_by_the_per_ip_limiter_but_other_routes_are():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from middleware.rate_limit import RateLimitMiddleware

    async def ok(request):
        return PlainTextResponse("ok")

    tiny = Starlette(routes=[Route("/api/insights/ingest", ok, methods=["POST"]), Route("/other", ok)])
    tiny.add_middleware(RateLimitMiddleware, requests_per_minute=1, burst=1)
    async with AsyncClient(transport=ASGITransport(app=tiny), base_url="http://x") as c:
        assert [(await c.post("/api/insights/ingest")).status_code for _ in range(20)] == [200] * 20
        assert [(await c.get("/other")).status_code for _ in range(3)] == [200, 429, 429]


@pytest.mark.asyncio
async def test_a_summary_is_reused_for_a_few_seconds_when_the_cache_is_on(auth_client, nobody, project, monkeypatch):
    from routers import agent_insights_stream as route

    monkeypatch.setenv("FORGE_INSIGHTS_SUMMARY_CACHE_S", "30")
    route._SUMMARY_CACHE.clear()
    key = await make_key(auth_client, project)
    await post(nobody, key, [t(1)])
    first = (await auth_client.get(base(project) + "/summary?range=24h")).json()
    await post(nobody, key, [t(2)])
    assert (await auth_client.get(base(project) + "/summary?range=24h")).json() == first                  # reused
    assert (await auth_client.get(base(project) + "/summary?range=24h&agent_id=support")).json() != first  # another view is its own entry
    monkeypatch.setenv("FORGE_INSIGHTS_SUMMARY_CACHE_S", "0")
    assert (await auth_client.get(base(project) + "/summary?range=24h")).json()["insights"]["totals"]["turns"] == 2
    route._SUMMARY_CACHE.clear()
