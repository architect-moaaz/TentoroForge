"""Scrape a URL's brand identity from its og:image meta tag."""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass
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


def scrape_brand_from_url(url: str, timeout: float = 8.0) -> ScrapedBrand | None:
    """Fetch the URL, parse og:image, run extract_palette_from_logo on the image bytes."""
    client = httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        resp = client.get(url)
        if resp.status_code != 200:
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
    title_match = _OG_TITLE_RE.search(html)
    title = title_match.group(1) if title_match else None

    try:
        img_resp = client.get(og_url)
        if img_resp.status_code != 200:
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
