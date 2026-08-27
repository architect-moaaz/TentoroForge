"""figma_asset_downloader.py

Utilities for extracting and locally caching Figma MCP CDN asset URLs.

MCP CDN URLs (figma.com/api/mcp/asset/...) expire after 7 days. This module
extracts them from JSX source, downloads them to output_dir/public/figma/,
and returns a mapping of URL → public path for use in schema rewriting.
"""

import asyncio
import hashlib
import pathlib
import re
from typing import Optional

import httpx

# Pattern matches MCP asset endpoints — both the hosted CDN
# (figma.com/api/mcp/asset/...) and the local Dev Mode MCP server
# (127.0.0.1:3845/assets/... or localhost:3845/assets/...).
#
# Fix B — the local Dev Mode MCP writes JSX with `src="http://localhost:3845/
# assets/<hash>.<ext>"`. Without matching this pattern, those srcs are never
# downloaded, so schema Image nodes stay pointing at a dev-only origin that
# 404s at runtime. Matching them here funnels them through the same
# download-and-rewrite path as the hosted CDN URLs.
_MCP_ASSET_PATTERN = re.compile(
    r'https://www\.figma\.com/api/mcp/asset/[A-Za-z0-9_\-]+'
    r'|https?://(?:127\.0\.0\.1|localhost):3845/assets/[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9]+)?'
)

# Maps content-type to file extension
_CONTENT_TYPE_EXT: dict[str, str] = {
    "image/svg+xml": ".svg",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

_KNOWN_EXTS = [".svg", ".png", ".jpg", ".gif", ".webp"]


def extract_asset_urls(jsx_source: str) -> list[str]:
    """Return unique MCP asset URLs (figma.com/api/mcp/asset/...) found
    in the jsx source. Skips non-MCP URLs.

    Returns a sorted, deduplicated list.
    """
    found = _MCP_ASSET_PATTERN.findall(jsx_source)
    return sorted(set(found))


async def download_figma_assets(
    urls: list[str],
    output_dir: str,
    concurrency: int = 8,
    project_id: str | None = None,
) -> dict[str, str]:
    """Download each URL to output_dir/public/figma/<sha1[:12]>.<ext>.

    Idempotent — skips existing files.

    When project_id is supplied, returns paths of the form
    ``/api/asset/<project_id>/figma/<file>`` so the render-scaffold can serve
    them via its per-project asset route handler.  When project_id is None,
    falls back to the legacy ``/figma/<file>`` form (used by tests / callers
    that don't know the project id yet).

    Accepts URLs from any source — MCP CDN, Figma REST `/v1/images` exports,
    or arbitrary public asset URLs. The hash-based filename means the
    function is content-source-agnostic; the URL is just the cache key.

    Failed downloads are silently omitted from the result.
    """
    figma_dir = pathlib.Path(output_dir) / "public" / "figma"
    figma_dir.mkdir(parents=True, exist_ok=True)

    if not urls:
        return {}

    semaphore = asyncio.Semaphore(concurrency)
    result: dict[str, str] = {}

    def _public_path(file_name: str) -> str:
        if project_id:
            return f"/api/asset/{project_id}/figma/{file_name}"
        return f"/figma/{file_name}"

    async def _download_one(client: httpx.AsyncClient, url: str) -> Optional[tuple[str, str]]:
        h = hashlib.sha1(url.encode()).hexdigest()[:12]

        # Idempotency: check if any cached file exists for this hash
        for ext in _KNOWN_EXTS:
            candidate = figma_dir / f"{h}{ext}"
            if candidate.exists():
                return url, _public_path(f"{h}{ext}")

        async with semaphore:
            try:
                resp = await client.get(url, follow_redirects=True, timeout=30.0)
                if resp.status_code != 200:
                    return None

                content_type = resp.headers.get("content-type", "").split(";")[0].strip()
                ext = _CONTENT_TYPE_EXT.get(content_type, ".svg")

                file_name = f"{h}{ext}"
                dest = figma_dir / file_name
                dest.write_bytes(resp.content)
                return url, _public_path(file_name)
            except Exception:
                return None

    async with httpx.AsyncClient() as client:
        tasks = [_download_one(client, url) for url in urls]
        outcomes = await asyncio.gather(*tasks)

    for outcome in outcomes:
        if outcome is not None:
            url, public_path = outcome
            result[url] = public_path

    return result
