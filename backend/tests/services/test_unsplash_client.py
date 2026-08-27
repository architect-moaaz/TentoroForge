"""Tests for the photo URL client (picsum.photos)."""
from __future__ import annotations
import tempfile
from pathlib import Path

from services.unsplash_client import UnsplashClient


def test_photo_url_returns_picsum_url_for_valid_query():
    """Deterministic picsum URL — same query, same image, every time."""
    with tempfile.TemporaryDirectory() as td:
        client = UnsplashClient(cache_dir=Path(td))
        url = client.photo_url_for_query("doctor", size="1600x900")
        assert url.startswith("https://picsum.photos/seed/")
        assert url.endswith("/1600/900")


def test_photo_url_is_deterministic_across_calls():
    """Same query → same URL on both calls (and same seed across processes —
    we hash the query rather than relying on Python's randomised hash())."""
    with tempfile.TemporaryDirectory() as td:
        client = UnsplashClient(cache_dir=Path(td))
        first = client.photo_url_for_query("doctor")
        second = client.photo_url_for_query("doctor")
        assert first == second


def test_photo_url_different_queries_different_urls():
    """Different queries → different picsum seeds → different image URLs."""
    with tempfile.TemporaryDirectory() as td:
        client = UnsplashClient(cache_dir=Path(td))
        a = client.photo_url_for_query("doctor")
        b = client.photo_url_for_query("nurse")
        assert a != b
        assert a.startswith("https://picsum.photos/seed/")
        assert b.startswith("https://picsum.photos/seed/")


def test_photo_url_respects_custom_size():
    with tempfile.TemporaryDirectory() as td:
        client = UnsplashClient(cache_dir=Path(td))
        url = client.photo_url_for_query("doctor", size="400x400")
        assert url.endswith("/400/400")


def test_photo_url_returns_fallback_on_invalid_size():
    """Malformed size returns the placeholder URL rather than crashing."""
    with tempfile.TemporaryDirectory() as td:
        client = UnsplashClient(cache_dir=Path(td))
        url = client.photo_url_for_query("doctor", size="not-a-size")
        assert url
        assert url.startswith("https://")


def test_clear_cache_removes_entries():
    with tempfile.TemporaryDirectory() as td:
        client = UnsplashClient(cache_dir=Path(td))
        client.photo_url_for_query("doctor")
        assert any(Path(td).iterdir())
        client.clear_cache()
        assert not any(Path(td).iterdir())
