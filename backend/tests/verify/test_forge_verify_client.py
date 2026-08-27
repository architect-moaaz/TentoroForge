"""Unit tests for services.forge_verify_client — SV-4."""
from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
import respx
from httpx import Response

from services.forge_verify_client import (
    ForgeVerifyClient,
    ForgeVerifyError,
    _to_jsonable,
)


@dataclass(frozen=True)
class _Simple:
    a: int
    b: tuple[str, ...]


def test_to_jsonable_flattens_dataclasses_and_tuples() -> None:
    got = _to_jsonable(_Simple(a=1, b=("x", "y")))
    assert got == {"a": 1, "b": ["x", "y"]}


def test_to_jsonable_recurses_into_nested_structures() -> None:
    got = _to_jsonable({"list": [_Simple(a=2, b=())]})
    assert got == {"list": [{"a": 2, "b": []}]}


@pytest.mark.asyncio
async def test_run_returns_run_id() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        rmock.post("http://runner/run").mock(
            return_value=Response(200, json={"run_id": "run_x"}),
        )
        async with ForgeVerifyClient(base_url="http://runner") as c:
            run_id = await c.run(
                project_id="p1", target="preview", base_url="http://app",
                interactions=[],
            )
        assert run_id == "run_x"


@pytest.mark.asyncio
async def test_run_raises_on_non_200() -> None:
    async with respx.mock() as rmock:
        rmock.post("http://runner/run").mock(
            return_value=Response(400, json={"error": "bad"}),
        )
        async with ForgeVerifyClient(base_url="http://runner") as c:
            with pytest.raises(ForgeVerifyError):
                await c.run(
                    project_id="p1", target="preview", base_url="http://app",
                    interactions=[],
                )


@pytest.mark.asyncio
async def test_run_raises_when_runner_unreachable() -> None:
    async with respx.mock() as rmock:
        rmock.post("http://runner/run").mock(side_effect=httpx.ConnectError("connect refused"))
        async with ForgeVerifyClient(base_url="http://runner") as c:
            with pytest.raises(ForgeVerifyError):
                await c.run(
                    project_id="p1", target="preview", base_url="http://app",
                    interactions=[],
                )


@pytest.mark.asyncio
async def test_healthz_true_on_ok() -> None:
    async with respx.mock() as rmock:
        rmock.get("http://runner/healthz").mock(
            return_value=Response(200, json={"ok": True}),
        )
        async with ForgeVerifyClient(base_url="http://runner") as c:
            assert await c.healthz() is True


@pytest.mark.asyncio
async def test_healthz_false_on_unreachable() -> None:
    async with respx.mock() as rmock:
        rmock.get("http://runner/healthz").mock(side_effect=httpx.ConnectError("boom"))
        async with ForgeVerifyClient(base_url="http://runner") as c:
            assert await c.healthz() is False
