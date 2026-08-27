"""Global exception handler — sanitizes error responses for production."""

import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import APP_ENV

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Catches unhandled exceptions and returns sanitized JSON error responses."""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            request_id = getattr(request.state, "request_id", "-")
            logger.exception(
                "Unhandled exception on %s %s [request_id=%s]",
                request.method,
                request.url.path,
                request_id,
            )

            # In dev, include the traceback; in production, sanitize
            if APP_ENV == "production":
                detail = "An internal error occurred. Please try again later."
            else:
                detail = f"{type(exc).__name__}: {exc}"

            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": detail,
                        "request_id": request_id,
                    }
                },
            )
