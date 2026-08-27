"""Structured JSON logging middleware with request_id, user_id, and duration tracking."""

import json
import time
import logging
import sys

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("tentoroforge.access")


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request as structured JSON with timing and context."""

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        request_id = getattr(request.state, "request_id", "-")

        # Extract user_id from token if available (set by auth)
        user_id = "-"

        response = await call_next(request)

        duration_ms = round((time.monotonic() - start) * 1000, 2)

        log_data = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "user_id": user_id,
            "client_ip": request.client.host if request.client else "-",
        }

        # Log level based on status code
        if response.status_code >= 500:
            logger.error(json.dumps(log_data))
        elif response.status_code >= 400:
            logger.warning(json.dumps(log_data))
        else:
            logger.info(json.dumps(log_data))

        return response


def setup_structured_logging(log_level: str = "INFO"):
    """Configure structured JSON logging for the application."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # JSON formatter for production
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredJsonFormatter())
    root.handlers = [handler]


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)
