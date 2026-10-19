"""Neon returns a new project before its branch and endpoint exist, and
answers every change with 423 Locked until they do. FitTrackr's first four
publishes (qpqhdugb, 2026-10-19) each made a project and died asking it for
the test database, leaving four projects behind. The client now waits for the
project's operations, retries a locked database creation, and the provider
records the project before asking anything else of it."""
from __future__ import annotations

import json

import httpx
import pytest

from services.deploy.neon_client import NeonClient


def _client(handler) -> NeonClient:
    c = NeonClient(api_key="k", org_id="o")
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://console.neon.tech")
    return c


@pytest.mark.asyncio
async def test_create_project_waits_until_its_operations_are_done(monkeypatch):
    calls: list[str] = []
    polls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.method} {req.url.path}")
        if req.method == "POST" and req.url.path == "/api/v2/projects":
            return httpx.Response(201, json={"project": {"id": "p1", "default_branch_id": "b1"},
                                             "connection_uris": [{"connection_uri": "postgres://x"}]})
        if req.url.path == "/api/v2/projects/p1/operations":
            polls["n"] += 1
            status = "running" if polls["n"] < 3 else "finished"
            return httpx.Response(200, json={"operations": [{"id": "op", "status": status}]})
        return httpx.Response(404)

    async def no_sleep(_):  # the waits are real time; the test is not
        return None
    import services.deploy.neon_client as mod
    monkeypatch.setattr(mod.asyncio, "sleep", no_sleep) if hasattr(mod, "asyncio") else None
    import asyncio
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    out = await _client(handler).create_project(name="qpqhdugb")
    assert out["project_id"] == "p1"
    assert polls["n"] == 3  # waited through two running polls
    assert calls[0] == "POST /api/v2/projects"


@pytest.mark.asyncio
async def test_a_locked_database_creation_is_retried_until_it_lands(monkeypatch):
    posts = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v2/projects/p1/branches":
            return httpx.Response(200, json={"branches": [{"id": "b1", "default": True}]})
        if req.url.path == "/api/v2/projects/p1/branches/b1/databases" and req.method == "GET":
            return httpx.Response(200, json={"databases": [{"name": "neondb"}]})
        if req.url.path == "/api/v2/projects/p1/branches/b1/databases" and req.method == "POST":
            posts["n"] += 1
            return httpx.Response(423, json={"message": "project is locked"}) if posts["n"] < 3 else httpx.Response(201, json={"database": {"name": "forge_test"}})
        if req.url.path == "/api/v2/projects/p1/operations":
            return httpx.Response(200, json={"operations": []})
        if req.url.path == "/api/v2/projects/p1/connection_uri":
            return httpx.Response(200, json={"uri": "postgres://forge_test"})
        return httpx.Response(404, json={"path": req.url.path})

    import asyncio
    async def no_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    made = await _client(handler).ensure_database("p1", "forge_test")
    assert made["created"] is True and posts["n"] == 3


def test_the_provider_records_the_project_before_asking_it_for_a_database():
    import inspect
    from services.deploy import vercel_provider
    src = inspect.getsource(vercel_provider)
    made = src.index('r = await self.neon.create_project(name=snapshot.project_slug)\n                    neon_project_id = r["project_id"]')
    asked = src.index("made = await self.neon.ensure_database(neon_project_id, envs.TEST_DATABASE)")
    recorded = src.index("row.neon_project_id = neon_project_id\n                    row.neon_branch_id = r.get(\"branch_id\")\n                    await self._flush()")
    assert made < recorded < asked
