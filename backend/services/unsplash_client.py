"""Cached photo URL client.

Originally targeted source.unsplash.com, which Unsplash deprecated mid-2023
(returns 503 / unreliable redirects). Switched to picsum.photos which:
  - is keyless,
  - returns a real image,
  - supports deterministic seeding via /seed/<text>/<w>/<h> (same query →
    same image, so regeneration produces stable previews),
  - and supports the size syntax we want.

The class name is preserved for backwards compatibility with existing
callers (photo_picker imports UnsplashClient).
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import httpx

_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "unsplash"
# Placeholder when even the deterministic URL is unreachable. Picsum's
# fixed-id endpoint is a known-good image URL.
_PLACEHOLDER_URL = "https://picsum.photos/id/237/1600/900"


def _seed_for(query: str) -> str:
    """Hash the query into a short URL-safe seed so the picsum URL is short
    and clean, and the same query always maps to the same seed (and thus the
    same image). picsum's /seed/<text>/ endpoint accepts arbitrary URL-safe
    strings — we use a 12-char sha1 prefix to keep it tidy."""
    return hashlib.sha1(query.encode()).hexdigest()[:12]


def _parse_size(size: str) -> tuple[int, int]:
    """Accept '1600x900' (preferred) or just '1600' (square)."""
    if "x" in size:
        w, h = size.split("x", 1)
        return int(w), int(h)
    n = int(size)
    return n, n


class UnsplashClient:
    """Cached photo URL client. Name retained for backwards compatibility."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, query: str, size: str) -> Path:
        key = hashlib.sha1(f"{query}|{size}".encode()).hexdigest()[:16]
        return self.cache_dir / f"{key}.url"

    def photo_url_for_query(self, query: str, size: str = "1600x900") -> str:
        cache = self._cache_path(query, size)
        if cache.exists():
            return cache.read_text().strip()

        try:
            w, h = _parse_size(size)
        except ValueError:
            return _PLACEHOLDER_URL

        url = f"https://picsum.photos/seed/{_seed_for(query)}/{w}/{h}"
        # No pre-verify — picsum doesn't accept HEAD (405), and a GET would
        # download the bytes. Consumers (Avatar.photoUrl, Hero.backgroundImage)
        # already handle load failures via onError fallback to initials /
        # solid background. Emit the URL and trust the cdn.
        cache.write_text(url)
        return url

    def clear_cache(self) -> None:
        for p in self.cache_dir.glob("*.url"):
            p.unlink()
