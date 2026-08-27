"""Redis connection and cache helpers."""

import json
import logging
from typing import Any

from config import REDIS_URL

logger = logging.getLogger(__name__)

_redis = None


async def get_redis():
    """Get or create Redis connection. Returns None if Redis is unavailable."""
    global _redis
    if _redis is not None:
        return _redis

    try:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        await _redis.ping()
        logger.info("Redis connected at %s", REDIS_URL)
        return _redis
    except Exception as e:
        logger.warning("Redis not available: %s — caching disabled", e)
        _redis = None
        return None


async def cache_get(key: str) -> Any | None:
    """Get a value from cache. Returns None on miss or if Redis is unavailable."""
    r = await get_redis()
    if not r:
        return None
    try:
        val = await r.get(key)
        if val is not None:
            return json.loads(val)
    except Exception:
        pass
    return None


async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> bool:
    """Set a value in cache with TTL. Returns False if Redis is unavailable."""
    r = await get_redis()
    if not r:
        return False
    try:
        await r.set(key, json.dumps(value), ex=ttl_seconds)
        return True
    except Exception:
        return False


async def cache_delete(key: str) -> bool:
    """Delete a key from cache."""
    r = await get_redis()
    if not r:
        return False
    try:
        await r.delete(key)
        return True
    except Exception:
        return False


async def cache_invalidate_pattern(pattern: str) -> int:
    """Delete all keys matching a pattern."""
    r = await get_redis()
    if not r:
        return 0
    try:
        keys = []
        async for key in r.scan_iter(match=pattern):
            keys.append(key)
        if keys:
            await r.delete(*keys)
        return len(keys)
    except Exception:
        return 0
