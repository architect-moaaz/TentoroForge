"""A published app whose post-publish check only warned is still a published app.

Iron Log was live at its address, and the mobile build said "No deployed URL is available for this project. Publish the web
app first": the publish had ended `succeeded_with_warnings` and the lookup asked for exactly `succeeded`."""
from __future__ import annotations

import asyncio
import types
import uuid

from models.deployment import LIVE_STATUSES
from routers import mobile_builds


class FakeSession:
    def __init__(self, sink):
        self.sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.sink.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
        return types.SimpleNamespace(scalar_one_or_none=lambda: "https://uaq6iu40.vercel.app")


def test_live_means_succeeded_or_succeeded_with_warnings():
    assert set(LIVE_STATUSES) == {"succeeded", "succeeded_with_warnings"}


def test_the_mobile_build_finds_the_address_of_an_app_published_with_a_warning(monkeypatch):
    sent = []
    monkeypatch.setattr(mobile_builds, "async_session", lambda: FakeSession(sent))
    url = asyncio.run(mobile_builds._latest_deployed_url(uuid.uuid4()))
    assert url == "https://uaq6iu40.vercel.app"
    sql = sent[0]
    assert "succeeded_with_warnings" in sql and "'succeeded'" in sql, "both live statuses are asked for"
    assert "'failed'" not in sql and "'pending'" not in sql
