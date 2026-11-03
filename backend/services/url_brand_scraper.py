"""Scrape a URL's brand identity from its og:image meta tag.

Every address it opens — the page, each redirect, the image the page names —
must be on the public internet (`services.smith.web._public_host`). It opened
whatever it was given and followed any redirect, so a pasted address could
read the cloud host's metadata service or the platform's own internal ports
(audit, 2026-11-01).
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
import httpx

from services.brand_extractor import extract_palette_from_logo, BrandPalette

logger = logging.getLogger(__name__)

_OG_IMAGE_RE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', re.IGNORECASE)
_OG_TITLE_RE = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', re.IGNORECASE)


@dataclass(frozen=True)
class ScrapedBrand:
    url: str
    title: str | None
    og_image_url: str
    primary_hex: str
    palette: BrandPalette


_REDIRECTS = (301, 302, 303, 307, 308)
_MAX_HOPS = 5


def _public(url: str) -> bool:
    from services.smith.web import _public_host

    parts = urlparse(url)
    return (parts.scheme in ("http", "https") and not parts.username and not parts.password
            and _public_host((parts.hostname or "").lower()))


def _get(client: httpx.Client, url: str):
    """GET, following redirects only to public addresses. None when refused."""
    for _ in range(_MAX_HOPS + 1):
        if not _public(url):
            logger.warning("scrape: %s is not on the public internet; not opened", url)
            return None
        resp = client.get(url)
        if resp.status_code not in _REDIRECTS:
            return resp
        url = urljoin(url, resp.headers.get("location") or "")
    return None


def scrape_brand_from_url(url: str, timeout: float = 8.0) -> ScrapedBrand | None:
    """Fetch the URL, parse og:image, run extract_palette_from_logo on the image bytes."""
    client = httpx.Client(timeout=timeout, follow_redirects=False)
    try:
        resp = _get(client, url)
        if resp is None or resp.status_code != 200:
            return None
        html = resp.text
    except httpx.RequestError as e:
        logger.warning("scrape: HTTP error on %s: %s", url, e)
        return None

    og_match = _OG_IMAGE_RE.search(html)
    if not og_match:
        return None
    og_url = og_match.group(1)
    if og_url.startswith("//"):
        og_url = "https:" + og_url
    og_url = urljoin(url, og_url)
    title_match = _OG_TITLE_RE.search(html)
    title = title_match.group(1) if title_match else None

    try:
        img_resp = _get(client, og_url)
        if img_resp is None or img_resp.status_code != 200:
            return None
        palette = extract_palette_from_logo(img_resp.content)
    except httpx.RequestError as e:
        logger.warning("scrape: og:image fetch failed for %s: %s", og_url, e)
        return None

    return ScrapedBrand(
        url=url,
        title=title,
        og_image_url=og_url,
        primary_hex=palette.primary_hex,
        palette=palette,
    )
