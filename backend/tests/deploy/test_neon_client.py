"""Unit tests for NeonClient — every REST call mocked via respx.

The 2026-07 Neon API requires an org_id on project creation for
personal API keys; this test suite locks that in so a regression
doesn't ship the "org_id is required" runtime error.
"""
from __future__ import annotations

import json as _json

import pytest
import respx
from httpx import Response

from services.deploy.neon_client import NeonClient


@pytest.mark.asyncio
async def test_create_project_sends_org_id_pg_version_region() -> None:
    """The core contract — every field the 2026-07 API mandates goes
    on the request; the returned dict exposes the ids the pipeline
    stores on the Deployment row."""
    async with respx.mock(assert_all_called=True) as rmock:
        route = rmock.post("https://console.neon.tech/api/v2/projects").mock(
            return_value=Response(
                200,
                json={
                    "project": {
                        "id": "np_123",
                        "name": "acme",
                        "default_branch_id": "br_1",
                    },
                    "connection_uris": [
                        {"connection_uri": "postgres://user:pass@ep.neon.tech/main"}
                    ],
                },
            )
        )
        c = NeonClient(api_key="nk", org_id="org-x")
        try:
            r = await c.create_project(name="acme", pg_version=18)
        finally:
            await c.close()

        assert r["project_id"] == "np_123"
        assert r["branch_id"] == "br_1"
        assert "postgres://" in r["database_url"]

        body = _json.loads(route.calls.last.request.content)
        assert body["project"]["name"] == "acme"
        assert body["project"]["pg_version"] == 18
        assert body["project"]["org_id"] == "org-x"
        assert body["project"]["region_id"] == "aws-us-east-2"


@pytest.mark.asyncio
async def test_create_project_defaults_to_pg18_when_unspecified() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        route = rmock.post("https://console.neon.tech/api/v2/projects").mock(
            return_value=Response(
                200,
                json={
                    "project": {"id": "np_1", "default_branch_id": "br_1"},
                    "connection_uris": [{"connection_uri": "postgres://x"}],
                },
            )
        )
        c = NeonClient(api_key="nk", org_id="org-x")
        try:
            await c.create_project(name="acme")
        finally:
            await c.close()
        body = _json.loads(route.calls.last.request.content)
        assert body["project"]["pg_version"] == 18


@pytest.mark.asyncio
async def test_delete_project_hits_delete_endpoint() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        route = rmock.delete(
            "https://console.neon.tech/api/v2/projects/np_123"
        ).mock(return_value=Response(200, json={"project": {"id": "np_123"}}))
        c = NeonClient(api_key="nk", org_id="org-x")
        try:
            await c.delete_project("np_123")
        finally:
            await c.close()
        assert route.called


@pytest.mark.asyncio
async def test_raises_on_non_2xx() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        rmock.post("https://console.neon.tech/api/v2/projects").mock(
            return_value=Response(
                400,
                json={"code": "", "message": "org_id is required"},
            )
        )
        c = NeonClient(api_key="nk", org_id=None)
        try:
            with pytest.raises(Exception):
                await c.create_project(name="acme")
        finally:
            await c.close()
