"""Tests for the thin Figma API wrapper (services/figma_client.py)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.figma_client import (
    fetch_figma_node, fetch_figma_file_meta, fetch_figma_file,
    fetch_figma_node_batched, fetch_figma_image_urls,
)


def _resp(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload or {})
    r.text = "Not Found"
    return r


@pytest.mark.asyncio
async def test_fetch_figma_node_returns_document():
    payload = {"nodes": {"1:2": {"document": {"id": "1:2", "name": "Frame"}}}}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(200, payload))) as mock_get:
        result = await fetch_figma_node("KEY", "1:2", "tok")
    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.figma.com/v1/files/KEY/nodes"
    assert kwargs["headers"]["X-Figma-Token"] == "tok"
    assert kwargs["params"] == {"ids": "1:2"}
    assert result == {"id": "1:2", "name": "Frame"}


@pytest.mark.asyncio
async def test_fetch_figma_node_raises_on_non_200():
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(404, {}))):
        with pytest.raises(RuntimeError, match="figma fetch failed: 404"):
            await fetch_figma_node("K", "1:2", "t")


@pytest.mark.asyncio
async def test_fetch_figma_node_returns_empty_dict_when_node_missing():
    """API returned 200 but the requested node isn't in the response — return {} rather than raising."""
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(200, {"nodes": {}}))):
        result = await fetch_figma_node("K", "1:2", "t")
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_figma_file_meta_uses_depth_1():
    payload = {"name": "Commitbiz-Design", "lastModified": "2026-05-15"}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(200, payload))) as mock_get:
        meta = await fetch_figma_file_meta("KEY", "tok")
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.figma.com/v1/files/KEY"
    assert kwargs["params"] == {"depth": 1}
    assert meta == payload


@pytest.mark.asyncio
async def test_fetch_figma_file_meta_raises_on_403():
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(403))):
        with pytest.raises(RuntimeError, match="figma meta fetch failed: 403"):
            await fetch_figma_file_meta("K", "t")


@pytest.mark.asyncio
async def test_fetch_figma_file_passes_depth():
    payload = {"name": "Commitbiz", "document": {"children": [{"id": "0:1", "type": "CANVAS"}]}}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(200, payload))) as mock_get:
        result = await fetch_figma_file("K", "tok", depth=2)
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.figma.com/v1/files/K"
    assert kwargs["params"] == {"depth": 2}
    assert kwargs["headers"]["X-Figma-Token"] == "tok"
    assert result == payload


@pytest.mark.asyncio
async def test_fetch_figma_file_default_depth_is_2():
    payload = {"name": "X"}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(200, payload))) as mock_get:
        await fetch_figma_file("K", "tok")
    assert mock_get.call_args.kwargs["params"] == {"depth": 2}


@pytest.mark.asyncio
async def test_fetch_figma_file_raises_on_non_200():
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(403))):
        with pytest.raises(RuntimeError, match="figma file fetch failed: 403"):
            await fetch_figma_file("K", "tok")


@pytest.mark.asyncio
async def test_fetch_figma_file_strips_token_whitespace():
    """Defensive — pasted tokens often have trailing whitespace."""
    payload = {"name": "X"}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(200, payload))) as mock_get:
        await fetch_figma_file("K", "  tok  ")
    assert mock_get.call_args.kwargs["headers"]["X-Figma-Token"] == "tok"


# ── fetch_figma_node_batched ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_figma_node_batched_returns_dict():
    """Each requested node id maps to its document subtree."""
    def make_payload(nid):
        return {"nodes": {nid: {"document": {"id": nid, "name": f"frame_{nid}"}}}}
    async def fake_get(url, params=None, headers=None):
        nid = params["ids"]
        return _resp(200, make_payload(nid))
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)):
        result = await fetch_figma_node_batched("K", ["1:2", "1:74", "1:505"], "tok")
    assert set(result.keys()) == {"1:2", "1:74", "1:505"}
    assert result["1:2"]["name"] == "frame_1:2"
    assert result["1:74"]["id"] == "1:74"


@pytest.mark.asyncio
async def test_fetch_figma_node_batched_handles_per_node_failure():
    """If one node fetch fails, others still complete; failed → empty dict."""
    async def fake_get(url, params=None, headers=None):
        nid = params["ids"]
        if nid == "BAD":
            return _resp(404, {})
        return _resp(200, {"nodes": {nid: {"document": {"id": nid}}}})
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)):
        result = await fetch_figma_node_batched("K", ["GOOD1", "BAD", "GOOD2"], "tok")
    assert result["GOOD1"]["id"] == "GOOD1"
    assert result["BAD"] == {}     # failure → empty dict, not raised
    assert result["GOOD2"]["id"] == "GOOD2"


@pytest.mark.asyncio
async def test_fetch_figma_node_batched_empty_list_returns_empty_dict():
    result = await fetch_figma_node_batched("K", [], "tok")
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_figma_node_batched_strips_token_whitespace():
    """Defensive — same pattern as fetch_figma_node."""
    captured_tokens = []
    async def fake_get(url, params=None, headers=None):
        captured_tokens.append(headers["X-Figma-Token"])
        nid = params["ids"]
        return _resp(200, {"nodes": {nid: {"document": {"id": nid}}}})
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)):
        await fetch_figma_node_batched("K", ["1:2"], "  tok  ")
    assert all(t == "tok" for t in captured_tokens)


# ── fetch_figma_image_urls ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_figma_image_urls_returns_dict_of_node_id_to_cdn_url():
    payload = {"images": {"1:2": "https://figma-alpha-api.s3.us-west-2.amazonaws.com/img1.svg",
                           "1:3": "https://figma-alpha-api.s3.us-west-2.amazonaws.com/img2.svg"}}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(200, payload))) as mock_get:
        result = await fetch_figma_image_urls("KEY", ["1:2", "1:3"], "tok")
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.figma.com/v1/images/KEY"
    assert kwargs["params"]["ids"] == "1:2,1:3"
    assert kwargs["params"]["format"] == "svg"
    assert kwargs["headers"]["X-Figma-Token"] == "tok"
    assert result == {
        "1:2": "https://figma-alpha-api.s3.us-west-2.amazonaws.com/img1.svg",
        "1:3": "https://figma-alpha-api.s3.us-west-2.amazonaws.com/img2.svg",
    }


@pytest.mark.asyncio
async def test_fetch_figma_image_urls_omits_null_entries():
    """Figma returns `null` for nodes it can't render — drop those."""
    payload = {"images": {"1:2": "https://x/img.svg", "1:3": None}}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(200, payload))):
        result = await fetch_figma_image_urls("K", ["1:2", "1:3"], "t")
    assert result == {"1:2": "https://x/img.svg"}


@pytest.mark.asyncio
async def test_fetch_figma_image_urls_batches_large_lists():
    """Calling with more ids than batch_size triggers multiple GETs."""
    payload1 = {"images": {f"id-{i}": f"https://x/{i}.svg" for i in range(60)}}
    payload2 = {"images": {f"id-{i}": f"https://x/{i}.svg" for i in range(60, 75)}}
    responses = [_resp(200, payload1), _resp(200, payload2)]
    call_count = {"i": 0}
    async def fake_get(*a, **kw):
        r = responses[call_count["i"]]
        call_count["i"] += 1
        return r
    ids = [f"id-{i}" for i in range(75)]
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)) as mock_get:
        result = await fetch_figma_image_urls("K", ids, "t", batch_size=60)
    assert mock_get.call_count == 2
    assert len(result) == 75


@pytest.mark.asyncio
async def test_fetch_figma_image_urls_empty_list_returns_empty_dict():
    """No GET should fire for an empty id list."""
    with patch("httpx.AsyncClient.get", AsyncMock()) as mock_get:
        result = await fetch_figma_image_urls("K", [], "t")
    mock_get.assert_not_called()
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_figma_image_urls_raises_on_non_200():
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(403, {}))):
        with pytest.raises(RuntimeError, match="figma image export failed"):
            await fetch_figma_image_urls("K", ["1:2"], "t")
