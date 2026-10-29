"""While a person who connected Figma is acting, every REST read is theirs.

The shared token opens only its owner's files: a client's project shared with
a tester read as "not found" for it (2026-10-29). `config_for` adds the acting
person's own token, `token_resolver` prefers it, it travels as an OAuth token
(`Authorization: Bearer`, which is the only header Figma reads one from), it is
refreshed before it runs out, and when Figma says 404/403 the person is told to
connect the account that can open the file.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

SHARED = "figd_" + "shared0token0of0the0platform0"
MINE = "figu_" + "mine0granted0by0signing0in0"
FRESH = "figu_" + "fresh0after0the0refresh0000"
EMAIL = "tess@studio.test"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A file-backed platform database: one person, connected to Figma."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'store.db'}"
    monkeypatch.setenv("FORGE_INTEGRATIONS_SECRET", "a" * 64)
    monkeypatch.setenv("FIGMA_OAUTH_CLIENT_ID", "forge-client")
    monkeypatch.setenv("FIGMA_OAUTH_CLIENT_SECRET", "forge-" + "secret-value")
    monkeypatch.setenv("FIGMA_TOKEN", SHARED)
    import config

    monkeypatch.setattr(config, "DATABASE_URL", url)

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from models.auth import PlatformUser
    from models.person_connection import PersonConnection
    from services.figma import oauth

    user_id = uuid.uuid4()

    def connect(expires_in: timedelta) -> None:
        async def fill() -> None:
            engine = create_async_engine(url)
            async with engine.begin() as conn:
                await conn.run_sync(lambda c: PlatformUser.__table__.create(c, checkfirst=True))
                await conn.run_sync(lambda c: PersonConnection.__table__.create(c, checkfirst=True))
            async with async_sessionmaker(engine)() as db:
                if await db.get(PlatformUser, user_id) is None:
                    db.add(PlatformUser(id=user_id, email=EMAIL, name="Tess"))
                    await db.commit()
                await oauth.save(db, user_id, oauth.Tokens(access_token=MINE, refresh_token="figur_" + "r" * 24,
                                                           expires_at=datetime.now(timezone.utc) + expires_in),
                                 {"id": "9", "handle": "Tess", "email": EMAIL})
            await engine.dispose()

        asyncio.run(fill())

    return connect


def _read_with(values: dict) -> str:
    from services.figma.integrations import token_resolver

    ref, resolver = token_resolver(values)
    return resolver.resolve(ref)


def test_the_acting_persons_token_is_read_with_and_the_shared_one_is_not(store, tmp_path):
    from services.build_usage import acting
    from services.figma.credentials import OAuthAccessToken
    from services.figma.integrations import config_for
    from services.figma_client import auth_headers

    store(timedelta(days=80))

    # Nobody acting (a check nobody asked for in person): the shared token.
    assert _read_with(config_for(tmp_path)) == SHARED
    assert auth_headers(_read_with(config_for(tmp_path))) == {"X-Figma-Token": SHARED}

    with acting(user=EMAIL.upper(), org=""):
        token = _read_with(config_for(tmp_path))
    assert token == MINE and isinstance(token, OAuthAccessToken)
    assert auth_headers(token) == {"Authorization": f"Bearer {MINE}"}
    assert MINE not in repr(token)

    # Someone else acting, who never connected: the shared token.
    with acting(user="other@studio.test"):
        assert _read_with(config_for(tmp_path)) == SHARED


def test_the_gateway_sends_the_persons_token_to_figma(store, tmp_path, monkeypatch):
    """The REST read itself: the node request carries the person's bearer token."""
    from services.build_usage import acting
    from services.figma.credentials import FigmaCredential
    from services.figma.gateway import FigmaGateway
    from services.figma.integrations import config_for, token_resolver
    import services.figma_client as fc

    store(timedelta(days=80))
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        return httpx.Response(200, json={"nodes": {"1:2": {"document": {"id": "1:2", "type": "FRAME"}}}})

    real = httpx.AsyncClient
    monkeypatch.setattr(fc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    with acting(user=EMAIL):
        ref, resolver = token_resolver(config_for(tmp_path))
    gateway = FigmaGateway(credential=FigmaCredential(ref=ref), resolver=resolver)
    doc = asyncio.run(gateway.rest_node(file_key="KEY", node_id="1:2"))

    assert doc["id"] == "1:2"
    assert seen[0]["authorization"] == f"Bearer {MINE}" and "x-figma-token" not in seen[0]


def test_a_token_near_its_end_is_refreshed_once_and_kept(store, tmp_path, monkeypatch):
    from services.figma import oauth

    store(timedelta(minutes=30))
    asked: list[dict] = []

    def post(url, data=None, headers=None, **_):
        asked.append({"url": url, "data": dict(data or {})})
        assert url.endswith("/v1/oauth/refresh") and headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, json={"access_token": FRESH, "token_type": "bearer", "expires_in": 7776000})

    monkeypatch.setattr(httpx, "post", post)

    got = oauth.person_token(EMAIL)
    assert got is not None and got.token == FRESH and got.account == "Tess"
    assert asked == [{"url": "https://api.figma.com/v1/oauth/refresh", "data": {"refresh_token": "figur_" + "r" * 24}}]

    # Stored: the next read takes the fresh token without asking Figma again.
    again = oauth.person_token(EMAIL)
    assert again is not None and again.token == FRESH and len(asked) == 1


def test_a_refused_refresh_keeps_the_token_while_it_still_works(store, monkeypatch):
    from services.figma import oauth

    store(timedelta(minutes=30))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(400, json={"error": "invalid_grant"}))
    got = oauth.person_token(EMAIL)
    assert got is not None and got.token == MINE


def test_an_expired_token_that_cannot_be_refreshed_falls_back_to_the_shared_one(store, tmp_path, monkeypatch):
    from services.build_usage import acting
    from services.figma.integrations import config_for

    store(timedelta(minutes=-5))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(400, json={"error": "invalid_grant"}))
    with acting(user=EMAIL):
        assert _read_with(config_for(tmp_path)) == SHARED


@pytest.mark.parametrize("status", [404, 403])
def test_figma_not_finding_the_file_tells_the_person_to_connect_the_account_that_can(status, monkeypatch):
    from services.figma.credentials import FigmaCredential
    from services.figma.gateway import FigmaGateway, FigmaGatewayError
    from services.figma.integrations import MappingResolver, PERSON_ACCOUNT_KEY, PERSON_TOKEN_KEY
    from services.smith.figma_connect import no_access_message
    import services.figma_client as fc

    real = httpx.AsyncClient
    monkeypatch.setattr(fc.httpx, "AsyncClient", lambda **kw: real(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"status": status, "err": "Not found"})), **kw))

    gateway = FigmaGateway(credential=FigmaCredential(ref="FIGMA_TOKEN"),
                           resolver=MappingResolver({"FIGMA_TOKEN": SHARED}))
    gateway._rest_preferred = True
    with pytest.raises(FigmaGatewayError) as raised:
        asyncio.run(gateway.call("get_metadata", file_key="ClientKey"))
    assert raised.value.kind == "no_access" and SHARED not in str(raised.value)

    shared = no_access_message({"FIGMA_TOKEN": SHARED})
    assert "Connect the Figma account that can open this file" in shared
    mine = no_access_message({PERSON_TOKEN_KEY: MINE, PERSON_ACCOUNT_KEY: "Tess"})
    assert "the Figma account you connected (Tess)" in mine and "Connect Figma again" in mine
    assert MINE not in mine and SHARED not in shared
