"""unDraw HTTP client with on-disk caching.

The MCP server wraps this client. Cache key is (slug, color). Once
a (slug, color) pair has been fetched and stored under cache_dir,
subsequent reads come from disk — no network roundtrip during a
generation, which makes the schema-agent fast and deterministic.

unDraw API:
  - Listing:   GET https://undraw.co/api/illustrations?page=N
  - Per-SVG:   GET https://undraw.co/illustrations/<slug>.svg?color=<hex>

Note: this module lives under ``illustrations_mcp`` (not ``mcp``) to
avoid colliding with the official ``mcp`` Python SDK package.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import logging

import httpx

logger = logging.getLogger(__name__)

_LISTING_URL = "https://undraw.co/api/illustrations"
_SVG_URL = "https://undraw.co/illustrations/{slug}.svg"


@dataclass(frozen=True)
class IllustrationMeta:
    slug: str
    title: str
    tags: list[str]


class UndrawClient:
    def __init__(self, cache_dir):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._http = httpx.Client(timeout=15.0)

    def list_illustrations(self, tags=None, limit=20):
        """Fetch one page of unDraw illustrations. Client-side filter by tags.

        unDraw's API doesn't accept tag query params — we paginate and
        filter locally. For v1 the LLM gets a single page of results;
        tighter filtering can paginate further if relevance is poor.
        """
        try:
            resp = self._http.get(_LISTING_URL)
        except httpx.HTTPError as e:
            logger.warning("undraw listing fetch failed: %s", e)
            return []
        if resp.status_code != 200:
            return []
        data = resp.json() or {}
        rows = data.get("illustrations") or data.get("media") or []
        results = []
        norm_tags = [t.lower() for t in (tags or [])]
        for row in rows:
            slug = row.get("slug") or row.get("id") or ""
            title = row.get("title") or slug
            row_tags = [t.lower() for t in (row.get("tags") or row.get("categories") or [])]
            if norm_tags and not (set(norm_tags) & set(row_tags)):
                continue
            results.append(IllustrationMeta(slug=slug, title=title, tags=row_tags))
            if len(results) >= limit:
                break
        return results

    def get_illustration_svg(self, slug, color="6b7280"):
        """Fetch (or return cached) SVG bytes for a slug + color.

        Color is a hex string without leading '#'. Cache key is
        '<slug>__<color>.svg'.
        """
        color = color.lstrip("#").lower()
        cache_path = self._cache_dir / f"{slug}__{color}.svg"
        if cache_path.exists():
            return cache_path.read_bytes()
        try:
            resp = self._http.get(_SVG_URL.format(slug=slug), params={"color": color})
        except httpx.HTTPError as e:
            logger.warning("undraw svg fetch failed for %s: %s", slug, e)
            return None
        if resp.status_code != 200:
            return None
        svg = resp.content
        cache_path.write_bytes(svg)
        return svg
