"""Thin httpx wrapper for the Figma REST API. Used by the deterministic
mapper (figma_to_schema) and any future Figma-aware service that needs a
clean per-call interface — distinct from backend/figma_tools.py which
exposes MCP-style tool functions.
"""
from __future__ import annotations

import asyncio

import httpx


FIGMA_BASE = "https://api.figma.com/v1"

#: How many times one request is tried when Figma says "too many" (429) or
#: fails on its side (5xx), and the longest single wait honoured.
RETRY_ATTEMPTS = 6
MAX_WAIT_S = 120.0


class FigmaRateLimited(RuntimeError):
    """Figma kept answering 429 after every wait it asked for.

    Separate from a plain failure so a caller reading a five-hundred-frame
    file can stop where it is and carry on later, instead of recording every
    remaining frame as missing."""


def _wait_for(r: httpx.Response, attempt: int) -> float:
    """What Figma asked for (Retry-After, in seconds), else a growing wait."""
    try:
        asked = float(r.headers.get("Retry-After") or 0)
    except (TypeError, ValueError):
        asked = 0.0
    return min(MAX_WAIT_S, asked if asked > 0 else 2.0 * (2 ** attempt))


async def _get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """One GET that waits out Figma's rate limit.

    FIGMA LIMITS PER MINUTE, AND SAYS FOR HOW LONG. A file of hundreds of
    frames is hundreds of requests on a token allowed a few dozen a minute;
    a 429 was a `RuntimeError` like any other, so the read died at the first
    one. Now a 429 or a 5xx waits — as long as `Retry-After` asks — and tries
    again; anything else is returned to the caller as before."""
    r = await client.get(url, **kwargs)
    for attempt in range(RETRY_ATTEMPTS - 1):
        if r.status_code != 429 and r.status_code < 500:
            return r
        await asyncio.sleep(_wait_for(r, attempt))
        r = await client.get(url, **kwargs)
    if r.status_code == 429:
        raise FigmaRateLimited(
            f"figma rate limited: 429 after {RETRY_ATTEMPTS} tries — the token's "
            "per-minute allowance is spent")
    return r


async def fetch_figma_node(file_key: str, node_id: str, token: str,
                           depth: int | None = None) -> dict:
    """Fetch one node's subtree — whole, or ``depth`` levels of it. Returns
    `nodes[node_id].document` or `{}` when the API returned 200 but didn't
    include the requested node."""
    token = (token or "").strip()
    params: dict = {"ids": node_id}
    if depth:
        params["depth"] = depth
    async with httpx.AsyncClient(timeout=30.0 if not depth else 120.0) as client:
        r = await _get(
            client, f"{FIGMA_BASE}/files/{file_key}/nodes",
            params=params,
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
        r = await _get(
            client, f"{FIGMA_BASE}/files/{file_key}",
            params={"depth": 1},
            headers={"X-Figma-Token": token},
        )
        if r.status_code != 200:
            raise RuntimeError(f"figma meta fetch failed: {r.status_code} {r.text[:200]}")
        return r.json()


async def fetch_figma_nodes(file_key: str, node_ids: list[str], token: str,
                            *, batch_size: int = 20) -> dict[str, dict]:
    """Many frames' full subtrees, several per request: ``{node id: document}``.

    `/files/{key}/nodes` takes a comma-separated `ids`, so a file of five
    hundred frames is twenty-five requests rather than five hundred — which is
    the difference between a read that finishes inside the token's per-minute
    allowance and one that waits out the limit for half an hour. A batch the
    API refuses as a whole (one huge frame can make the answer too large) is
    halved until it is answered; a frame refused alone comes back as ``{}``.
    A rate limit that outlasts every wait raises :class:`FigmaRateLimited`.
    """
    token = (token or "").strip()
    out: dict[str, dict] = {}
    if not node_ids:
        return out

    async def one_batch(client: httpx.AsyncClient, ids: list[str]) -> None:
        r = await _get(client, f"{FIGMA_BASE}/files/{file_key}/nodes",
                       params={"ids": ",".join(ids)}, headers={"X-Figma-Token": token})
        if r.status_code != 200:
            if len(ids) > 1 and r.status_code not in (401, 403, 404):
                half = len(ids) // 2
                await one_batch(client, ids[:half])
                await one_batch(client, ids[half:])
                return
            if r.status_code in (401, 403):
                raise RuntimeError(f"figma fetch failed: {r.status_code} {r.text[:200]}")
            for nid in ids:
                out[nid] = {}
            return
        nodes = (r.json() or {}).get("nodes") or {}
        for nid in ids:
            out[nid] = ((nodes.get(nid) or {}).get("document")) or {}

    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(0, len(node_ids), batch_size):
            await one_batch(client, list(node_ids[i:i + batch_size]))
    return out


async def download_images(urls: dict[str, str], *, concurrency: int = 8) -> dict[str, bytes]:
    """``{node id: png bytes}`` from the render URLs `/images` handed back.

    The renders are on Figma's CDN, not the API, so they do not count against
    the token's allowance and are fetched several at a time. A render that
    will not download is left out — a frame without a picture is still a
    frame."""
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, bytes] = {}

    async with httpx.AsyncClient(timeout=60.0) as client:
        async def one(nid: str, url: str) -> None:
            async with sem:
                try:
                    r = await _get(client, url)
                except Exception:  # noqa: BLE001 — a render is optional
                    return
                if r.status_code == 200:
                    out[nid] = r.content

        await asyncio.gather(*(one(n, u) for n, u in urls.items()))
    return out


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
            r = await _get(
                client, f"{FIGMA_BASE}/images/{file_key}",
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
        r = await _get(
            client, f"{FIGMA_BASE}/files/{file_key}",
            params={"depth": depth},
            headers={"X-Figma-Token": token},
        )
        if r.status_code != 200:
            raise RuntimeError(f"figma file fetch failed: {r.status_code} {r.text[:200]}")
        return r.json()
