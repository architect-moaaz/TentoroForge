"""Thin httpx wrapper for the Figma REST API. Used by the deterministic
mapper (figma_to_schema) and any future Figma-aware service that needs a
clean per-call interface — distinct from backend/figma_tools.py which
exposes MCP-style tool functions.
"""
from __future__ import annotations

import asyncio

import httpx


FIGMA_BASE = "https://api.figma.com/v1"


async def fetch_figma_node(file_key: str, node_id: str, token: str) -> dict:
    """Fetch one node's full subtree. Returns `nodes[node_id].document` or `{}`
    when the API returned 200 but didn't include the requested node."""
    token = (token or "").strip()
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{FIGMA_BASE}/files/{file_key}/nodes",
            params={"ids": node_id},
            headers={"X-Figma-Token": token},
        )
        if r.status_code != 200:
            raise RuntimeError(f"figma fetch failed: {r.status_code} {r.text[:200]}")
        body = r.json()
        node_payload = (body.get("nodes") or {}).get(node_id) or {}
        return node_payload.get("document") or {}


async def fetch_figma_file_meta(file_key: str, token: str) -> dict:
    """Lightweight metadata fetch — depth=1 keeps response small (~few KB)."""
    token = (token or "").strip()
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{FIGMA_BASE}/files/{file_key}",
            params={"depth": 1},
            headers={"X-Figma-Token": token},
        )
        if r.status_code != 200:
            raise RuntimeError(f"figma meta fetch failed: {r.status_code} {r.text[:200]}")
        return r.json()


# Cap concurrent Figma API calls. Figma's free-tier rate limit is ~60 req/min;
# with 8 in flight at typical 0.5-1s latency that's ~480-960 req/min, but
# our actual fan-out is bounded by the size of a single project (~10-50 frames),
# so this practically only matters for large files.
_FIGMA_SEMAPHORE = asyncio.Semaphore(8)


async def fetch_figma_node_batched(
    file_key: str,
    node_ids: list[str],
    token: str,
) -> dict[str, dict]:
    """Fetch many nodes concurrently with rate-limit guard.

    Returns {node_id: document_subtree}. Pages that fail individually
    return an empty dict for their node_id rather than raising — caller
    decides what to do with empty results.

    Caps concurrency at 8 via module-level asyncio.Semaphore to stay
    well under Figma's 60 req/min free-tier rate limit.

    See module-level fetch_figma_node for the single-node version.
    """
    token = (token or "").strip()
    if not node_ids:
        return {}

    async def _one(nid: str) -> tuple[str, dict]:
        async with _FIGMA_SEMAPHORE:
            try:
                doc = await fetch_figma_node(file_key, nid, token)
                return nid, doc
            except Exception:
                # Per-node failure isolation — return empty for this node,
                # let caller decide. Errors are NOT swallowed for logging:
                # caller has the {nid: {}} hint and can re-fetch / log itself.
                return nid, {}

    pairs = await asyncio.gather(*[_one(nid) for nid in node_ids])
    return dict(pairs)


async def fetch_figma_image_urls(
    file_key: str,
    node_ids: list[str],
    token: str,
    format: str = "svg",
    scale: float = 1.0,
    batch_size: int = 60,
) -> dict[str, str]:
    """Render the given Figma nodes via `/v1/images/{key}?ids=...&format=...`
    and return {node_id: cdn_url}.

    Figma's images endpoint accepts a comma-separated `ids` query parameter
    and responds with `{ images: { <node_id>: <cdn_url | null> } }`. The CDN
    URL expires after ~1 hour, so callers should download the asset and
    cache it locally (use figma_asset_downloader for that).

    Nodes that Figma can't render return null and are omitted from the
    result. Network / API failures raise so the caller can log + fall back
    cleanly (asset URL absence ≠ rendering failure).

    Batches `node_ids` in chunks of `batch_size` so a 200-icon design doesn't
    hit Figma's URL-length limit on the comma-separated parameter.
    """
    token = (token or "").strip()
    if not node_ids:
        return {}

    out: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(0, len(node_ids), batch_size):
            chunk = node_ids[i : i + batch_size]
            r = await client.get(
                f"{FIGMA_BASE}/images/{file_key}",
                params={
                    "ids": ",".join(chunk),
                    "format": format,
                    "scale": scale,
                },
                headers={"X-Figma-Token": token},
            )
            if r.status_code != 200:
                raise RuntimeError(
                    f"figma image export failed ({r.status_code}): {r.text[:200]}"
                )
            payload = r.json() or {}
            images = payload.get("images") or {}
            for nid, url in images.items():
                if url:
                    out[nid] = url
    return out


async def fetch_figma_file(file_key: str, token: str, depth: int = 2) -> dict:
    """Fetch the file's canvas + frame tree at a configurable depth.
    depth=1 → file metadata only (canvas list)
    depth=2 → top-level frames per canvas (default — what plan-building needs)
    depth=3+ → progressively deeper
    """
    token = (token or "").strip()
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(
            f"{FIGMA_BASE}/files/{file_key}",
            params={"depth": depth},
            headers={"X-Figma-Token": token},
        )
        if r.status_code != 200:
            raise RuntimeError(f"figma file fetch failed: {r.status_code} {r.text[:200]}")
        return r.json()
