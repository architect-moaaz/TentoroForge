"""Live activity: a super admin watches what a person is doing as it happens,
and sees the action and which record — never their private values. Nothing
is stored; an event reaches whoever is watching at that instant and is gone.
The watch crosses workers over Redis, and a request for someone nobody is
watching publishes nothing."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from services import live_activity as LA


# --- a fake Redis with just the pub/sub and sets this uses -----------------
class _FakePubSub:
    def __init__(self, bus):
        self.bus = bus
        self.channels: set[str] = set()
        self.q: asyncio.Queue = asyncio.Queue()

    async def subscribe(self, ch):
        self.channels.add(ch)
        self.bus.subs.setdefault(ch, set()).add(self.q)

    async def unsubscribe(self, ch):
        self.channels.discard(ch)
        self.bus.subs.get(ch, set()).discard(self.q)

    async def aclose(self):
        for ch in list(self.channels):
            await self.unsubscribe(ch)

    async def get_message(self, ignore_subscribe_messages=True, timeout=None):
        try:
            return await asyncio.wait_for(self.q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None


class _FakeRedis:
    def __init__(self):
        self.sets: dict[str, set] = {}
        self.subs: dict[str, set] = {}

    async def sadd(self, k, v):
        self.sets.setdefault(k, set()).add(v)

    async def srem(self, k, v):
        self.sets.get(k, set()).discard(v)

    async def scard(self, k):
        return len(self.sets.get(k, set()))

    async def smembers(self, k):
        return set(self.sets.get(k, set()))

    async def expire(self, k, ttl):
        return True

    async def publish(self, ch, data):
        for q in list(self.subs.get(ch, set())):
            q.put_nowait({"data": data})

    def pubsub(self):
        return _FakePubSub(self)


@pytest.fixture
def fake(monkeypatch):
    r = _FakeRedis()

    async def _redis():
        return r

    monkeypatch.setattr(LA, "_redis", _redis)
    LA._watched.clear()
    yield r
    LA._watched.clear()


# --- what is shown, and what is not ----------------------------------------
def test_the_label_drops_the_query_and_scrubs_secrets():
    # A search someone typed lives in the query string — it never shows.
    assert LA.path_label("GET", "/api/data/Transaction?q=divorce+lawyer") == "Reading app data"
    lbl = LA.path_label("GET", "/api/orgs/abc/unknown?token=sk-ant-abcdefghijklmnop12345")
    assert "sk-ant-" not in lbl and "divorce" not in lbl
    assert LA.path_label("POST", "/api/projects/p1/smith/turn") == "Chatting with Smith"
    assert LA.path_label("POST", "/api/projects/p1/publish") == "Publishing an app"


def test_an_event_carries_the_action_and_ids_but_no_body():
    e = LA.build_event(user="u1", method="GET", path="/api/data/Transaction?q=secret", status=200, org="o1", by="admin1")
    assert e["user"] == "u1" and e["status"] == 200 and e["org"] == "o1" and e["by"] == "admin1"
    assert e["label"] == "Reading app data" and "?" not in e["path"] and "secret" not in json.dumps(e)


def test_the_stream_itself_and_the_pings_are_not_watched():
    assert LA.worth_streaming("/api/projects/p1/smith/turn")
    assert not LA.worth_streaming("/api/admin/live/u1")
    assert not LA.worth_streaming("/api/projects/p1/events")
    assert not LA.worth_streaming("/health")


# --- the watch, and the gate -----------------------------------------------
@pytest.mark.asyncio
async def test_nothing_is_emitted_for_a_person_nobody_watches(fake):
    seen = []
    ps = fake.pubsub()
    await ps.subscribe(LA._CHANNEL.format(uid="u1"))
    await LA.emit(LA.build_event(user="u1", method="GET", path="/x", status=200))
    assert await ps.get_message(timeout=0.05) is None  # not watched → not published
    assert not LA.is_watched("u1")


@pytest.mark.asyncio
async def test_a_watched_persons_action_reaches_the_watcher(fake):
    assert await LA.start_watch("u1", "admin1") is True
    assert LA.is_watched("u1") and "u1" in fake.sets[LA._WATCHED_SET]

    got = []

    async def reader():
        async for ev in LA.stream("u1"):
            if ev.get("type") == "activity":
                got.append(ev)
                return

    task = asyncio.ensure_future(reader())
    await asyncio.sleep(0.05)
    await LA.emit(LA.build_event(user="u1", method="POST", path="/api/projects/p1/publish", status=200, by="admin1"))
    await asyncio.wait_for(task, timeout=1)
    assert got and got[0]["label"] == "Publishing an app" and got[0]["by"] == "admin1"


@pytest.mark.asyncio
async def test_the_watch_ends_only_when_the_last_watcher_leaves(fake):
    await LA.start_watch("u1", "a")
    await LA.start_watch("u1", "b")
    assert await fake.scard(LA._WATCHERS.format(uid="u1")) == 2
    await LA.stop_watch("u1", "a")
    assert LA.is_watched("u1") and "u1" in fake.sets[LA._WATCHED_SET]
    await LA.stop_watch("u1", "b")
    assert not LA.is_watched("u1") and "u1" not in fake.sets[LA._WATCHED_SET]


@pytest.mark.asyncio
async def test_without_redis_it_is_a_quiet_no_op(monkeypatch):
    async def _none():
        return None
    monkeypatch.setattr(LA, "_redis", _none)
    LA._watched.clear()
    assert await LA.start_watch("u1", "a") is False
    assert await LA.available() is False
    await LA.emit(LA.build_event(user="u1", method="GET", path="/x", status=200))  # no raise


# --- the middleware gate ----------------------------------------------------
def test_identify_reads_the_person_and_the_admin_behind_them():
    from jose import jwt
    from config import JWT_ALGORITHM, SECRET_KEY
    from middleware.live_activity import _identify

    plain = jwt.encode({"sub": "u1", "type": "access"}, SECRET_KEY, algorithm=JWT_ALGORITHM)
    acting = jwt.encode({"sub": "u1", "act": "admin1", "type": "access"}, SECRET_KEY, algorithm=JWT_ALGORITHM)
    req = lambda tok: SimpleNamespace(headers={"authorization": f"Bearer {tok}"})
    assert _identify(req(plain)) == ("u1", None)
    assert _identify(req(acting)) == ("u1", "admin1")
    assert _identify(SimpleNamespace(headers={})) is None
    assert _identify(SimpleNamespace(headers={"authorization": "Bearer nonsense"})) is None
