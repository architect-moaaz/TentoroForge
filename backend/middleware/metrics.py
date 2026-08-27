"""Prometheus-style metrics middleware — request duration, status codes, agent costs."""

import time
import logging
from collections import defaultdict
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collects application metrics in-memory."""

    def __init__(self):
        self.request_count: dict[str, int] = defaultdict(int)
        self.request_duration_sum: dict[str, float] = defaultdict(float)
        self.request_duration_count: dict[str, int] = defaultdict(int)
        self.status_codes: dict[int, int] = defaultdict(int)
        self.agent_cost_total: float = 0
        self.agent_calls_total: int = 0
        self.active_requests: int = 0

    def record_request(self, method: str, path: str, status: int, duration_ms: float):
        key = f"{method}:{self._normalize_path(path)}"
        self.request_count[key] += 1
        self.request_duration_sum[key] += duration_ms
        self.request_duration_count[key] += 1
        self.status_codes[status] += 1

    def record_agent_cost(self, cost_usd: float):
        self.agent_cost_total += cost_usd
        self.agent_calls_total += 1

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []

        lines.append("# HELP http_requests_total Total HTTP requests")
        lines.append("# TYPE http_requests_total counter")
        for key, count in sorted(self.request_count.items()):
            method, path = key.split(":", 1)
            lines.append(f'http_requests_total{{method="{method}",path="{path}"}} {count}')

        lines.append("")
        lines.append("# HELP http_request_duration_ms_sum Sum of request durations in ms")
        lines.append("# TYPE http_request_duration_ms_sum counter")
        for key, total in sorted(self.request_duration_sum.items()):
            method, path = key.split(":", 1)
            lines.append(f'http_request_duration_ms_sum{{method="{method}",path="{path}"}} {total:.2f}')

        lines.append("")
        lines.append("# HELP http_status_codes_total Total responses by status code")
        lines.append("# TYPE http_status_codes_total counter")
        for code, count in sorted(self.status_codes.items()):
            lines.append(f'http_status_codes_total{{status="{code}"}} {count}')

        lines.append("")
        lines.append("# HELP agent_cost_usd_total Total AI agent cost in USD")
        lines.append("# TYPE agent_cost_usd_total counter")
        lines.append(f"agent_cost_usd_total {self.agent_cost_total:.6f}")

        lines.append("")
        lines.append("# HELP agent_calls_total Total AI agent invocations")
        lines.append("# TYPE agent_calls_total counter")
        lines.append(f"agent_calls_total {self.agent_calls_total}")

        lines.append("")
        lines.append("# HELP http_active_requests Currently active requests")
        lines.append("# TYPE http_active_requests gauge")
        lines.append(f"http_active_requests {self.active_requests}")

        return "\n".join(lines) + "\n"

    def _normalize_path(self, path: str) -> str:
        """Normalize path to avoid cardinality explosion from UUIDs."""
        import re
        # Replace UUIDs with placeholder
        path = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "{id}",
            path,
        )
        # Replace short IDs (8 char alphanumeric after /projects/)
        path = re.sub(r"/projects/[a-z0-9]{8}(?=/|$)", "/projects/{id}", path)
        return path


# Singleton metrics collector
metrics = MetricsCollector()


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records per-request metrics."""

    async def dispatch(self, request: Request, call_next):
        # Skip metrics endpoint itself
        if request.url.path == "/metrics":
            return await call_next(request)

        metrics.active_requests += 1
        start = time.monotonic()

        try:
            response = await call_next(request)
            duration_ms = (time.monotonic() - start) * 1000
            metrics.record_request(
                request.method, request.url.path, response.status_code, duration_ms
            )
            return response
        finally:
            metrics.active_requests -= 1


def metrics_endpoint(request: Request):
    """Prometheus metrics endpoint handler."""
    return PlainTextResponse(
        content=metrics.to_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
