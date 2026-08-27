"""Rate limiting middleware — in-memory token bucket with per-IP tracking."""

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    rate: float  # tokens per second
    capacity: float
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self):
        self.tokens = self.capacity
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting using an in-memory token bucket.

    Args:
        app: ASGI application
        requests_per_minute: Max requests per minute per IP (default 120)
        burst: Max burst size (default 20)
    """

    def __init__(self, app, requests_per_minute: int = 1200, burst: int = 200):
        super().__init__(app)
        self.rate = requests_per_minute / 60.0
        self.capacity = burst
        self._buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(rate=self.rate, capacity=self.capacity)
        )
        self._cleanup_counter = 0

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks
        if request.url.path in ("/health", "/ready", "/metrics"):
            return await call_next(request)
        # SSE streams: one connection lives for minutes but the browser
        # frequently reopens them (nav, HMR, StrictMode double-mount).
        # Counting each reopen against the bucket starves the whole chat
        # UI when the user only pinged the tab a few times. Skip.
        p = request.url.path
        if p.endswith("/events") or p.endswith("/verify/events") or p.endswith("/stream"):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        bucket = self._buckets[client_ip]

        if not bucket.consume():
            logger.warning("Rate limit exceeded for IP %s on %s", client_ip, request.url.path)
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests. Please try again later."}},
                headers={"Retry-After": str(int(60 / self.rate))},
            )

        # Periodic cleanup of old buckets
        self._cleanup_counter += 1
        if self._cleanup_counter >= 1000:
            self._cleanup_old_buckets()
            self._cleanup_counter = 0

        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _cleanup_old_buckets(self):
        now = time.monotonic()
        stale_keys = [
            k for k, v in self._buckets.items()
            if now - v.last_refill > 300  # 5 minutes idle
        ]
        for k in stale_keys:
            del self._buckets[k]
