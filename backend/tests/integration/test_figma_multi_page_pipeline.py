"""Integration test for the multi-page deterministic Figma mapper.

Confirms that fetch_figma_node_batched isolates per-node failures so a
single bad frame doesn't prevent sibling frames from emitting schemas."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _resp(status: int, payload: dict | None = None):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload or {})
    r.text = "Not Found"
    return r


@pytest.mark.asyncio
async def test_one_bad_node_does_not_kill_sibling_fetches():
    """fetch_figma_node_batched: middle node 404s; flanking nodes succeed."""
    from services.figma_client import fetch_figma_node_batched

    async def fake_get(url, params=None, headers=None):
        nid = params["ids"]
        if nid == "1:BAD":
            return _resp(404, {})
        return _resp(200, {"nodes": {nid: {"document": {
            "id": nid, "type": "FRAME", "name": f"frame_{nid}",
        }}}})

    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)):
        result = await fetch_figma_node_batched(
            "K", ["1:1", "1:BAD", "1:3"], "tok",
        )
    assert result["1:1"]["id"] == "1:1"
    assert result["1:BAD"] == {}      # bad one returns empty, not raises
    assert result["1:3"]["id"] == "1:3"


@pytest.mark.asyncio
async def test_build_page_schema_handles_each_doc_independently():
    """When build_page_schema receives an empty doc (failed fetch), it
    returns a result with complete=False and an empty page — callers
    can skip writing it without crashing."""
    from services.figma_to_schema import build_page_schema
    result = build_page_schema({})
    # Empty doc → empty children list, but no exception
    assert result.page.get("children") == [{"id": "empty", "type": "Stack", "props": {}, "children": []}] \
        or result.page.get("children") == []


@pytest.mark.asyncio
async def test_concurrent_fetches_respect_semaphore_cap():
    """All requests fan out concurrently but no more than 8 run at once."""
    from services.figma_client import fetch_figma_node_batched
    import asyncio as _aio
    in_flight = 0
    max_observed = 0
    lock = _aio.Lock()

    async def fake_get(url, params=None, headers=None):
        nonlocal in_flight, max_observed
        async with lock:
            in_flight += 1
            max_observed = max(max_observed, in_flight)
        await _aio.sleep(0.01)
        async with lock:
            in_flight -= 1
        nid = params["ids"]
        return _resp(200, {"nodes": {nid: {"document": {"id": nid}}}})

    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)):
        # Request 20 nodes — well over the 8-concurrent cap
        result = await fetch_figma_node_batched(
            "K", [f"1:{i}" for i in range(20)], "tok",
        )
    assert len(result) == 20
    assert max_observed <= 8, f"semaphore breached: {max_observed} concurrent"
