"""Shared test fixtures for backend integration tests.

NOTE: These tests require 'aiosqlite' to be installed for SQLite async testing.
Run: pip install aiosqlite
"""

import os
import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Override DATABASE_URL to use in-memory SQLite before importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ANTHROPIC_API_KEY"] = "test-key"

# ---------------------------------------------------------------------------
# The rate limiter is a WALL-CLOCK token bucket, and the suite shares one.
#
# `middleware/rate_limit.py` keeps a per-IP bucket — burst 20, refilling at
# 2/sec — and every TestClient request in the run arrives from the same IP
# against the same app instance. So the suite's HTTP budget depends on how
# fast the suite happens to run: shave ten seconds off the total and requests
# that used to arrive after a refill now arrive before one.
#
# The symptom is a test asserting 200 and getting 429, in a file nobody
# touched, reproducible in a full run and passing in isolation. Adding tests
# ANYWHERE can cause it, which makes it read as "your change broke this" when
# the change was in a module with no HTTP surface at all.
#
# Nothing tests this middleware (test_auth's 429 is `auth.py`'s login lockout,
# which is unrelated), so the limit is simply lifted here. A test that does
# want to exercise it should build its own middleware instance with its own
# numbers rather than racing the shared one.
# ---------------------------------------------------------------------------
os.environ.setdefault("RATE_LIMIT_REQUESTS_PER_MINUTE", "1000000")
os.environ.setdefault("RATE_LIMIT_BURST", "1000000")

# ---------------------------------------------------------------------------
# .env isolation: config.py and main.py call load_dotenv() at import time.
# Any test module that (transitively) imports them — pytest imports EVERY
# collected module, even ones -k later deselects — would dump the
# developer's backend/.env (FORGE_* feature flags, live API keys) into
# os.environ for the whole test process, so flag-gated code paths behave
# differently depending on which files happened to be collected. Tests must
# see flag defaults; flag-specific tests opt in via monkeypatch.setenv.
# This conftest is imported before any test module, so the no-op lands
# before config/main resolve `from dotenv import load_dotenv`.
# ---------------------------------------------------------------------------
import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False

# ---------------------------------------------------------------------------
# SQLite compatibility shim: map PostgreSQL-specific types to TEXT so that
# Base.metadata.create_all works against the in-memory SQLite test engine.
# ---------------------------------------------------------------------------
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler  # noqa: E402

def _visit_JSONB(self, type_, **kw):  # noqa: N802
    return "TEXT"

def _visit_INET(self, type_, **kw):  # noqa: N802
    return "TEXT"

def _visit_ARRAY(self, type_, **kw):  # noqa: N802
    return "TEXT"

SQLiteTypeCompiler.visit_JSONB = _visit_JSONB
SQLiteTypeCompiler.visit_INET = _visit_INET
SQLiteTypeCompiler.visit_ARRAY = _visit_ARRAY


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _strip_pg_only_server_defaults(metadata):
    """Neutralize PG-specific server_defaults SQLite can't compile.

    Applies to:
      * ``nextval('...'::regclass)`` — Postgres sequence
      * ``gen_random_uuid()``       — pgcrypto function

    Sets the column's ``default`` (Python-side) to a UUID generator
    when we're stripping ``gen_random_uuid()`` on a UUID PK so
    ``session.add(...)`` still gets a value. Sequence columns
    (``BIGINT`` seq) can safely be null in tests.
    """
    import re
    import uuid as _uuid
    from sqlalchemy.dialects.postgresql import UUID as _PGUUID
    from sqlalchemy.schema import ColumnDefault as _ColumnDefault

    sequence_re = re.compile(r"nextval\(.+?::regclass\)", re.IGNORECASE)
    uuid_re = re.compile(r"gen_random_uuid\(\)", re.IGNORECASE)

    for table in metadata.tables.values():
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            expr = getattr(sd, "arg", None)
            if expr is None:
                continue
            # Server-defaults can be TextClause (has ``.text``) OR any
            # ClauseElement whose ``str()`` renders the SQL (Function
            # nodes like ``gen_random_uuid()`` land here). str() is the
            # common denominator.
            text_val = getattr(expr, "text", None)
            if not isinstance(text_val, str):
                try:
                    text_val = str(expr)
                except Exception:  # noqa: BLE001
                    continue
            if sequence_re.search(text_val):
                col.server_default = None
            elif uuid_re.search(text_val):
                col.server_default = None
                if isinstance(col.type, _PGUUID) and col.default is None:
                    # Wrap the callable in ColumnDefault so SQLAlchemy
                    # treats it as a Python-side default and not a SQL
                    # construct to be compiled.
                    col.default = _ColumnDefault(_uuid.uuid4)


@pytest_asyncio.fixture
async def test_db():
    """Create fresh in-memory tables for each test."""
    from database import Base, engine

    _strip_pg_only_server_defaults(Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(test_db):
    """Async HTTP client hitting the FastAPI app."""
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient):
    """Client with a valid auth token (creates a test user)."""
    resp = await client.post("/api/auth/signup", json={
        "email": "test@example.com",
        "name": "Test User",
        "password": "Testpass123",
    })
    assert resp.status_code == 201, f"Signup failed: {resp.text}"
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client


@pytest_asyncio.fixture
async def org_id(auth_client: AsyncClient) -> str:
    """Create a test organization and return its ID."""
    resp = await auth_client.post("/api/orgs", json={
        "name": "Test Org",
        "slug": "test-org",
    })
    assert resp.status_code in (200, 201), f"Org creation failed: {resp.text}"
    return resp.json()["id"]
