from pathlib import Path

import pytest

from services.render_service.cache import RenderCache


@pytest.fixture
def cache(tmp_path: Path) -> RenderCache:
    return RenderCache(root=tmp_path)


def test_cache_miss_returns_none(cache: RenderCache):
    assert cache.get("anykey") is None


def test_cache_set_and_get_round_trips_bytes(cache: RenderCache):
    cache.set("k1", b"PNGDATA")
    assert cache.get("k1") == b"PNGDATA"


def test_cache_invalidate_removes_entry(cache: RenderCache):
    cache.set("k2", b"X")
    cache.invalidate("k2")
    assert cache.get("k2") is None


def test_cache_clear_empties_all(cache: RenderCache):
    cache.set("a", b"1")
    cache.set("b", b"2")
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_cache_make_key_is_deterministic():
    k1 = RenderCache.make_key({"projectId": "abc", "page": "/x", "viewport": "desktop"})
    k2 = RenderCache.make_key({"viewport": "desktop", "page": "/x", "projectId": "abc"})
    assert k1 == k2  # Order-independent
